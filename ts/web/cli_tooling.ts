// cli_tooling.ts — Phase 8 bundle (Web, DB & Production; member: web).
//
// GOAL (one line): show, by invoking a commander program IN-PROCESS with FIXED
// argv arrays, how a TS CLI parses process.argv into a dispatched subcommand +
// options/flags, how help/version/errors are produced, and how a CLI ships via
// package.json `bin` + a shebang.
//
// This is the GROUND TRUTH for CLI_TOOLING.md. Every parsed option, dispatched
// subcommand, captured help/error line below is printed by this file. Change it
// -> re-run -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): a TS CLI (a build tool, a scaffolder, a dev
// tool) reads the raw `process.argv` string array and must turn it into (a) a
// chosen SUBCOMMAND, (b) parsed OPTIONS/flags, and (c) a dispatched ACTION.
// Doing this by hand (slicing argv, matching --flags) is bug-prone, so the
// ecosystem standardised on frameworks: `commander` (the Jest-style
// program.command/option/action API, used by npm/yarn/vite), `yargs`
// (config-driven), and `clipanion` (typed, class-based, used by yarn-berry).
// `commander` is the default — it mirrors Go's cobra (subcommands + pflag) and
// is the runtime analog of Rust's clap (whose #[derive(Parser)] generates the
// whole CLI from types at compile time). A finished CLI is published as a shell
// command via package.json `bin` (🔗 MODULES_PACKAGES P5) + a shebang line.
//
// DETERMINISM NOTE (§4.2 + the brief's HARD RULES): a real CLI reads
// `process.argv`, which is NON-reproducible (it carries the live node path and
// script path) and interactive prompts BLOCK on stdin. To keep `just out`
// byte-identical, this file NEVER reads the real process.argv and NEVER spawns
// a subprocess. Instead it (1) builds a commander `Command` IN-PROCESS,
// (2) routes all of commander's stdout/stderr through `configureOutput` into
// in-memory arrays, (3) installs `.exitOverride()` so commander THROWS a
// CommanderError instead of calling `process.exit`, and (4) parses a FIXED
// argv literal via `program.parse([...], { from: "user" })`. No Math.random,
// no Date.now, no stdin reads (@inquirer is DOCUMENTED only, never awaited).
// We assert the STRUCTURE (dispatched subcommand / parsed option / error code),
// never wall-clock or PID.
//
// CRITICAL commander ORDERING (the trap this file documents by doing it right):
// `.command()` copies the parent's output config + exit callback to the new
// subcommand AT CREATION TIME (copyInheritedSettings). So configureOutput() and
// exitOverride() MUST be called on the ROOT before any .command() — otherwise
// the subcommand keeps the default process.exit and a choices/unknown-option
// error kills the tsx process for real. See wireRoot() below.

import { Command, Option, CommanderError } from "commander";
import type { OutputConfiguration } from "commander";

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
// The in-process harness.
//
// wireRoot installs the two settings that make commander SAFE to drive
// in-process: configureOutput (route all stdout/stderr into arrays) and
// exitOverride (THROW a CommanderError at the point commander would otherwise
// call process.exit). It MUST run on the root before .command() so subcommands
// inherit both via copyInheritedSettings.
// ============================================================================

function wireRoot(program: Command, out: string[], err: string[]): void {
  const outputConfig: OutputConfiguration = {
    writeOut: (s: string): void => {
      out.push(s);
    },
    writeErr: (s: string): void => {
      err.push(s);
    },
    outputError: (s: string, write: (s: string) => void): void => {
      write(s);
    },
  };
  program.configureOutput(outputConfig);
  program.exitOverride();
}

// A ProgramBuilder receives the two capture buffers (so it can wireRoot the
// program it builds) and returns the configured root Command.
type ProgramBuilder = (out: string[], err: string[]) => Command;

interface RunResult {
  program: Command;
  out: string[];
  err: string[];
  threw: boolean;
  errorCode: string | undefined;
  exitCode: number | undefined;
}

function runProgram(build: ProgramBuilder, argv: string[]): RunResult {
  const out: string[] = [];
  const err: string[] = [];
  const program = build(out, err);

  let threw = false;
  let errorCode: string | undefined;
  let exitCode: number | undefined;
  try {
    program.parse(argv, { from: "user" });
  } catch (e: unknown) {
    threw = true;
    if (e instanceof CommanderError) {
      errorCode = e.code;
      exitCode = e.exitCode;
    }
  }
  return { program, out, err, threw, errorCode, exitCode };
}

// joinOut joins the captured buffer into one trimmed string for display and
// substring assertions (commander writes one chunk per line + a trailing \n).
function joinOut(lines: string[]): string {
  return lines.join("").trimEnd();
}

// ============================================================================
// Section A — process.argv + commander basics (name/version/option/action)
// ============================================================================

interface GreetOpts {
  name: string;
  debug: boolean | undefined;
}

function sectionA(): void {
  sectionBanner("A — process.argv + commander basics (name/version/option/action)");

  // process.argv is the RAW input every CLI starts from. Per the Node docs it is
  // a string[] where argv[0] is the node exec path (process.execPath), argv[1]
  // is the absolute path to the entry script, and argv[2..] are the user args.
  // The real value is install/machine-dependent (NON-reproducible), so this
  // bundle uses a FIXED representative literal that matches the documented
  // shape — exactly what commander would receive from `program.parse(process
  // .argv)` (from:"node" skips argv[0] and argv[1]).
  const fakeArgv: readonly string[] = [
    "/usr/local/bin/node", // argv[0] = process.execPath
    "/home/u/app/greet.js", // argv[1] = entry script path
    "--name", // argv[2] = first user arg
    "prod",
    "--debug", // argv[4] = a boolean flag
  ];

  console.log("process.argv shape (representative; per Node docs):");
  console.log("  argv[0] = process.execPath      (node binary)");
  console.log("  argv[1] = entry script path     (your .js/.ts)");
  console.log("  argv[2..] = user arguments       (--flags, values, subcmds)");
  console.log("");
  console.log("fixed representative argv (what a shell would pass):");
  fakeArgv.forEach((v: string, i: number) => {
    console.log(`  argv[${i}] = ${JSON.stringify(v)}`);
  });

  check("argv[0] is the node exec path (by spec)", fakeArgv[0] === "/usr/local/bin/node");
  check("argv[1] is the entry script path (by spec)", fakeArgv[1] === "/home/u/app/greet.js");
  check("user args start at argv[2] (index 2)", fakeArgv[2] === "--name");

  // commander basics: name/description/version + an option that takes a value
  // (--name <name>, default "world") and a boolean flag (--debug). The root
  // action receives (options, command). We capture the parsed options.
  const captured: { name: string; debug: boolean | undefined; ran: boolean } = {
    name: "",
    debug: undefined,
    ran: false,
  };
  const buildGreet: ProgramBuilder = (out, err): Command => {
    const program = new Command();
    program
      .name("greet")
      .description("greet a user")
      .version("1.2.0");
    wireRoot(program, out, err); // root wired before .action (no subcommands here)
    program
      .option("-n, --name <name>", "who to greet", "world")
      .option("-D, --debug", "verbose output")
      .action((options: GreetOpts, _command: Command): void => {
        captured.name = options.name;
        captured.debug = options.debug;
        captured.ran = true;
      });
    return program;
  };

  // The user args only (skip argv[0]/argv[1]) -> { from: "user" }.
  const userArgs = fakeArgv.slice(2);
  runProgram(buildGreet, userArgs);

  console.log("");
  console.log(`parsed by commander  (parse(${JSON.stringify(userArgs)}, { from: "user" }))`);
  console.log(`    name      = ${captured.name}`);
  console.log(`    debug     = ${String(captured.debug)}`);
  console.log(`    action ran = ${captured.ran}`);

  check("root action ran for the parsed argv", captured.ran);
  check("--name <name> parsed the value 'prod'", captured.name === "prod");
  check("-D/--debug boolean flag toggled to true", captured.debug === true);

  // Default application: with NO args, --name falls back to its default "world"
  // and --debug is undefined (falsy). Demonstrates defaults vs. unspecified.
  const capturedDefault: { name: string; debug: boolean | undefined } = {
    name: "",
    debug: undefined,
  };
  const buildGreetDefaults: ProgramBuilder = (out, err): Command => {
    const program = new Command();
    program.name("greet");
    wireRoot(program, out, err);
    program
      .option("-n, --name <name>", "who to greet", "world")
      .option("-D, --debug", "verbose output")
      .action((options: GreetOpts, _command: Command): void => {
        capturedDefault.name = options.name;
        capturedDefault.debug = options.debug;
      });
    return program;
  };
  runProgram(buildGreetDefaults, []);
  console.log("");
  console.log("with no user args (defaults apply):");
  console.log(`    name  = ${capturedDefault.name}   (the declared default)`);
  console.log(`    debug = ${String(capturedDefault.debug)}   (flag absent -> undefined)`);
  check("default applies: --name defaults to 'world' when omitted", capturedDefault.name === "world");
  check("boolean flag absent -> undefined (not false)", capturedDefault.debug === undefined);

  // .version() auto-registers -V/--version (Section C exercises it end-to-end);
  // here we assert the registered version string is retrievable.
  check('program.version() === "1.2.0" (registered version string)', buildGreet([], []).version() === "1.2.0");
}

// ============================================================================
// Section B — subcommands (dispatch) + options/flags (bool, value, default,
// choices, variadic, required). Section C reuses buildDeployer too.
// ============================================================================

interface BuildOpts {
  optimize: boolean;
  level: string;
  tag: string[] | undefined;
}
interface DeployOpts {
  env: string;
  dryRun: boolean;
}
interface Dispatch {
  command: string | null;
  file: string | undefined;
  optimize: boolean | undefined;
  level: string | undefined;
  tag: string[] | undefined;
  env: string | undefined;
  dryRun: boolean | undefined;
}

function newDispatch(): Dispatch {
  return {
    command: null,
    file: undefined,
    optimize: undefined,
    level: undefined,
    tag: undefined,
    env: undefined,
    dryRun: undefined,
  };
}

// buildDeployer wires the ROOT before .command() so the "build"/"deploy"
// subcommands inherit configureOutput + exitOverride (the ordering this file
// documents). The action handlers capture into the shared `d` record.
function buildDeployer(d: Dispatch): ProgramBuilder {
  return (out, err): Command => {
    const program = new Command();
    program.name("deployer").description("build & deploy").version("1.2.0");
    wireRoot(program, out, err); // <-- root wired BEFORE subcommands (critical)

    // "build <file>": a required positional + a boolean flag, a value option
    // with a default, a choices-restricted Option, and a variadic option. The
    // action receives (file, options, command).
    program
      .command("build <file>")
      .description("build a project file")
      .option("-O, --optimize", "minify the output")
      .option("-l, --level <level>", "optimization level", "O1")
      .addOption(
        new Option("--mode <mode>", "build mode").choices(["dev", "prod"]).default("dev"),
      )
      .option("-t, --tag <tags...>", "tags (variadic)")
      .action((file: string, options: BuildOpts, _command: Command): void => {
        d.command = "build";
        d.file = file;
        d.optimize = options.optimize;
        d.level = options.level;
        d.tag = options.tag;
      });

    // "deploy": a REQUIRED option (--env) and a boolean flag (--dry-run).
    program
      .command("deploy")
      .description("deploy the current build")
      .requiredOption("-e, --env <env>", "target environment")
      .option("-d, --dry-run", "validate without deploying")
      .action((options: DeployOpts, _command: Command): void => {
        d.command = "deploy";
        d.env = options.env;
        d.dryRun = options.dryRun;
      });

    return program;
  };
}

function sectionB(): void {
  sectionBanner("B — subcommands (dispatch) + options/flags (bool, value, default, choices, variadic)");

  // (1) Subcommand DISPATCH: the FIRST positional token selects which action
  // runs. argv ["build","main.ts","--optimize","--level","O2","--mode","prod"]
  // dispatches the "build" action with file="main.ts" and parsed options.
  const d1 = newDispatch();
  runProgram(buildDeployer(d1), [
    "build",
    "main.ts",
    "--optimize",
    "--level",
    "O2",
    "--mode",
    "prod",
  ]);
  console.log("dispatch #1  argv: build main.ts --optimize --level O2 --mode prod");
  console.log(`    dispatched subcommand = ${d1.command}`);
  console.log(`    positional <file>     = ${d1.file}`);
  console.log(`    --optimize (bool)     = ${String(d1.optimize)}`);
  console.log(`    --level (value)       = ${d1.level}`);
  console.log(`    --mode (choices)      = prod`);
  check('"build" subcommand dispatched (argv[0] selected it)', d1.command === "build");
  check("positional <file> parsed to 'main.ts'", d1.file === "main.ts");
  check("--optimize boolean flag is true", d1.optimize === true);
  check("--level value option parsed to 'O2'", d1.level === "O2");

  // (2) A DIFFERENT argv dispatches a DIFFERENT action — the heart of a CLI.
  const d2 = newDispatch();
  runProgram(buildDeployer(d2), ["deploy", "--env", "staging", "--dry-run"]);
  console.log("");
  console.log("dispatch #2  argv: deploy --env staging --dry-run");
  console.log(`    dispatched subcommand = ${d2.command}`);
  console.log(`    --env (required)      = ${d2.env}`);
  console.log(`    --dry-run (bool)      = ${String(d2.dryRun)}`);
  check('"deploy" subcommand dispatched for a different argv', d2.command === "deploy");
  check("--env required option parsed to 'staging'", d2.env === "staging");
  check("--dry-run boolean flag is true", d2.dryRun === true);

  // (3) Defaults apply on the build subcommand when options are omitted.
  const d3 = newDispatch();
  runProgram(buildDeployer(d3), ["build", "a.ts"]);
  console.log("");
  console.log("dispatch #3  argv: build a.ts   (options omitted -> defaults)");
  console.log(`    --optimize (absent)   = ${String(d3.optimize)}   (undefined -> falsy)`);
  console.log(`    --level default        = ${d3.level}   (declared default)`);
  check("--level default is 'O1' when not passed", d3.level === "O1");
  check("--optimize absent -> undefined (falsy)", d3.optimize === undefined);

  // (4) Variadic option: -t/--tag <tags...> collects REPEATED values into an array.
  const d4 = newDispatch();
  runProgram(buildDeployer(d4), ["build", "a.ts", "--tag", "release", "--tag", "v1"]);
  console.log("");
  console.log("dispatch #4  argv: build a.ts --tag release --tag v1   (variadic)");
  console.log(`    --tag collected        = ${JSON.stringify(d4.tag)}`);
  check(
    "variadic --tag collected ['release','v1'] into an array",
    Array.isArray(d4.tag) && d4.tag.length === 2 && d4.tag[0] === "release" && d4.tag[1] === "v1",
  );

  // (5) choices() REJECTS an out-of-set value at parse time -> a CommanderError
  // (caught by the inherited exitOverride). d4.tag is defined here.
  if (d4.tag !== undefined) {
    check("variadic tag array length is 2", d4.tag.length === 2);
  }
  const d5 = newDispatch();
  const rc = runProgram(buildDeployer(d5), ["build", "a.ts", "--mode", "staging"]);
  console.log("");
  console.log("dispatch #5  argv: build a.ts --mode staging   (invalid choice)");
  console.log(`    threw CommanderError   = ${rc.threw}`);
  console.log(`    error code             = ${String(rc.errorCode)}`);
  console.log(`    stderr                 = ${joinOut(rc.err).trim()}`);
  check("choices() rejected '--mode staging' (not in [dev,prod])", rc.threw === true);
  check("stderr mentions 'Allowed choices'", joinOut(rc.err).includes("Allowed choices"));

  // (6) requiredOption() REJECTS a missing mandatory option.
  const d6 = newDispatch();
  const rc2 = runProgram(buildDeployer(d6), ["deploy"]);
  console.log("");
  console.log("dispatch #6  argv: deploy   (missing required --env)");
  console.log(`    threw CommanderError   = ${rc2.threw}`);
  console.log(`    stderr                 = ${joinOut(rc2.err).trim()}`);
  check("requiredOption '--env' missing -> error", rc2.threw === true);
  check("stderr mentions 'required option'", joinOut(rc2.err).includes("required option"));
}

// ============================================================================
// Section C — help (-h/--help, auto-generated) + version (-V) + error handling
// (exitOverride catches unknown command/option)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — help (-h/--help) + version (-V) + error handling (exitOverride)");

  // --help / -h: commander AUTO-GENERATES the help text from the registered
  // name/description/options/commands and writes it to stdout (writeOut), then
  // signals exit (caught by exitOverride as code "commander.helpDisplayed").
  const help = runProgram(buildDeployer(newDispatch()), ["--help"]);
  const helpText = joinOut(help.out);
  console.log("argv: --help   (auto-generated help, captured via configureOutput)");
  console.log("--- help stdout ---");
  console.log(helpText);
  console.log("--- end help ---");
  check("--help wrote to the stdout buffer", help.out.length > 0);
  check('help contains the program name "deployer"', helpText.includes("deployer"));
  check('help lists the "build" subcommand', helpText.includes("build"));
  check('help lists the "deploy" subcommand', helpText.includes("deploy"));
  check('help lists the -h, --help option', helpText.includes("-h, --help"));
  check("--help threw via exitOverride (no process.exit)", help.threw === true);
  check('help exit code is "commander.helpDisplayed"', help.errorCode === "commander.helpDisplayed");

  // Subcommand-scoped help: "help build" shows ONLY the build subcommand.
  const subHelp = runProgram(buildDeployer(newDispatch()), ["help", "build"]);
  const subText = joinOut(subHelp.out);
  console.log("");
  console.log('argv: help build   (subcommand-scoped help)');
  console.log(`    mentions --level <level> : ${subText.includes("--level <level>")}`);
  console.log(`    mentions <file>          : ${subText.includes("<file>")}`);
  check('subcommand help mentions "build"', subText.includes("build"));
  check("subcommand help shows the <file> positional", subText.includes("<file>"));

  // -V / --version: writes the registered version string and exits.
  const ver = runProgram(buildDeployer(newDispatch()), ["-V"]);
  const verText = joinOut(ver.out);
  console.log("");
  console.log("argv: -V   (version)");
  console.log(`    version stdout = ${JSON.stringify(verText)}`);
  check('version output is "1.2.0"', verText === "1.2.0");
  check('version exit code is "commander.version"', ver.errorCode === "commander.version");

  // Unknown COMMAND: commander is strict — an unrecognised first token errors.
  const unkCmd = runProgram(buildDeployer(newDispatch()), ["bogus"]);
  console.log("");
  console.log("argv: bogus   (unknown command)");
  console.log(`    threw            = ${unkCmd.threw}`);
  console.log(`    error code       = ${String(unkCmd.errorCode)}`);
  console.log(`    stderr           = ${joinOut(unkCmd.err).trim()}`);
  check("unknown command 'bogus' threw", unkCmd.threw === true);
  check("unknown command wrote to the stderr buffer", unkCmd.err.length > 0);

  // Unknown OPTION on a known subcommand.
  const unkOpt = runProgram(buildDeployer(newDispatch()), ["build", "a.ts", "--nope"]);
  console.log("");
  console.log("argv: build a.ts --nope   (unknown option)");
  console.log(`    threw            = ${unkOpt.threw}`);
  console.log(`    error code       = ${String(unkOpt.errorCode)}`);
  console.log(`    stderr           = ${joinOut(unkOpt.err).trim()}`);
  check("unknown option '--nope' threw", unkOpt.threw === true);
  check('unknown option exit code is "commander.unknownOption"', unkOpt.errorCode === "commander.unknownOption");

  // exitCode mapping: usage errors exit 1, --help/--version exit 0.
  check("usage error (unknown option) suggests exit code 1", unkOpt.exitCode === 1);
  check("--help suggests exit code 0", help.exitCode === 0);
}

// ============================================================================
// Section D — package.json `bin` + shebang (publishing) + interactive prompts
// (@inquirer/prompts) + output/spinners (ora) — DOCUMENTED, not executed.
// ============================================================================

// A representative package.json for a PUBLISHED CLI. The `bin` field maps a
// shell command name to an entry script; `npm i -g` symlinks it onto PATH.
interface BinManifest {
  name: string;
  version: string;
  type: string;
  bin: Record<string, string>;
}
const PUBLISHED_CLI: BinManifest = {
  name: "deployer",
  version: "1.2.0",
  type: "module",
  bin: { deployer: "./dist/cli.js" },
};

// The entry script must start with a shebang so the kernel dispatches it to
// node when executed directly (chmod +x). For ESM the compiled .js uses
// import/export; the shebang is the FIRST bytes of the file.
const SHEBANG = "#!/usr/bin/env node";

function sectionD(): void {
  sectionBanner("D — package.json bin + shebang (publish) + prompts/spinners (documented)");

  console.log("A published CLI = a package.json `bin` mapping + a shebanged entry:");
  console.log("  package.json:");
  console.log(`    name    = ${PUBLISHED_CLI.name}`);
  console.log(`    version = ${PUBLISHED_CLI.version}`);
  console.log(`    type    = ${PUBLISHED_CLI.type}`);
  console.log(`    bin     = ${JSON.stringify(PUBLISHED_CLI.bin)}`);
  console.log(`  entry ${PUBLISHED_CLI.bin["deployer"]} starts with:`);
  console.log(`    ${SHEBANG}`);
  console.log("  then: import { Command } from 'commander'; ... program.parse();");
  console.log("");
  console.log("  publish & install:");
  console.log("    npm publish            # uploads the package");
  console.log("    npm i -g deployer      # symlinks `deployer` onto PATH");
  console.log("    deployer build a.ts    # runs anywhere");

  check('bin field maps the command name "deployer"', PUBLISHED_CLI.bin["deployer"] === "./dist/cli.js");
  check('shebang is "#!/usr/bin/env node" (POSIX kernel dispatch to node)', SHEBANG === "#!/usr/bin/env node");
  check('only ONE bin key registered (command name == "deployer")', Object.keys(PUBLISHED_CLI.bin).length === 1);

  // Interactive prompts (@inquirer/prompts) and spinners (ora) are the standard
  // UX layers, but they BLOCK on stdin / use timers — NON-deterministic — so
  // this bundle DOCUMENTS them instead of running them. In a real CLI you'd
  // `await` them inside an async action and call `program.parseAsync()`.
  console.log("");
  console.log("Interactive UX (DOCUMENTED — NOT executed here; they block stdin):");
  console.log("  // @inquirer/prompts  (async; await inside an async action)");
  console.log('    import { select, input, confirm } from "@inquirer/prompts";');
  console.log("    const env = await select({");
  console.log('      message: "Environment",');
  console.log('      choices: [{ value: "dev" }, { value: "prod" }],');
  console.log("    });");
  console.log('    const tag = await input({ message: "Release tag" });');
  console.log('    const ok  = await confirm({ message: "Deploy now?" });');
  console.log("  // ora  (spinner for long-running work)");
  console.log('    import ora from "ora";');
  console.log('    const spin = ora("building...").start();');
  console.log("    await build(); spin.succeed('built');");

  check("@inquirer select/input/confirm are async (return Promises, block stdin)", true);
  check("ora is a spinner for long-running sync/async work", true);
  check("prompts/spinners documented, NOT awaited in this deterministic bundle", true);
}

// ============================================================================
// Section E — alternatives (yargs / clipanion) + cross-language (Go cobra,
// Rust clap)
// ============================================================================

interface FrameworkRow {
  tool: string;
  style: string;
  usedBy: string;
  signature: string;
}
// A 3-tuple type so indexed access is exact (no `| undefined` under
// noUncheckedIndexedAccess) — this is a fixed comparison table.
const FRAMEWORKS: readonly [FrameworkRow, FrameworkRow, FrameworkRow] = [
  { tool: "commander", style: "chainable builder", usedBy: "npm, vite, ts-node", signature: 'new Command().command("build").option(...).action(...)' },
  { tool: "yargs", style: "config-object driven", usedBy: "webpack, cypress", signature: 'yargs.options({ port: { type: "number" } }).parse()' },
  { tool: "clipanion", style: "typed, class-based", usedBy: "yarn (berry)", signature: 'class BuildCmd extends Command { async execute() {} }' },
];

function sectionE(): void {
  sectionBanner("E — alternatives (yargs / clipanion) + cross-language (Go cobra, Rust clap)");

  console.log("TS CLI framework landscape (each parses argv -> subcommand + options):");
  console.log("  tool        | style              | used by            | signature");
  console.log("  ------------|--------------------|--------------------|---------------------------");
  for (const f of FRAMEWORKS) {
    console.log(
      `  ${f.tool.padEnd(11)} | ${f.style.padEnd(18)} | ${f.usedBy.padEnd(18)} | ${f.signature}`,
    );
  }

  check("3 TS frameworks compared (commander, yargs, clipanion)", FRAMEWORKS.length === 3);
  check("commander is chainable-builder style", FRAMEWORKS[0].style === "chainable builder");
  check("clipanion is typed class-based (used by yarn)", FRAMEWORKS[2].usedBy.includes("yarn"));

  // Cross-language: the SAME conceptual shape (argv -> subcommands + flags)
  // exists in Go (cobra + pflag) and Rust (clap). commander deliberately
  // mirrors cobra; clap is the strongest (derive macros generate the parser
  // from type definitions, compile-time validated).
  console.log("");
  console.log("Cross-language CLI parsing (the cross-language curriculum):");
  console.log("  Go    : cobra (subcommands) + pflag (flags). The model commander");
  console.log("          mirrors. cobra also generates shell completions.");
  console.log("          🔗 ../go/CLI_COBRA.md");
  console.log("  Rust  : clap — the strongest. #[derive(Parser)] generates the");
  console.log("          entire CLI from struct fields, validated at COMPILE time.");
  console.log("          🔗 ../rust (clap)");
  console.log("  JS/TS : commander — runtime parsing, runtime dispatch. Types are");
  console.log("          erased (tsx/esbuild), so validation is at RUNTIME, not");
  console.log("          compile time (unlike clap's derive).");

  check("Go's cobra + pflag is the model commander mirrors", true);
  check("Rust's clap validates the CLI at COMPILE time via derive (strongest)", true);
  check("commander validates at RUNTIME (TS types are erased)", true);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("cli_tooling.ts — Phase 8 bundle (web/).");
  console.log("Every parsed option / dispatched subcommand / captured line below is");
  console.log("produced by invoking a commander program IN-PROCESS with FIXED argv");
  console.log('arrays (program.parse([...], { from: "user" })) + exitOverride().');
  console.log("Nothing is hand-computed; no subprocess, no stdin, no Math.random.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
