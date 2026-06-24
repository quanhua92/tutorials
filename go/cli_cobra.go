//go:build ignore

// cli_cobra.go — Phase 7 bundle.
//
// GOAL (one line): show, by driving cobra programmatically with root.SetArgs +
// root.SetOut + root.Execute (no os.Args, no real terminal), how a cobra command
// tree dispatches, how local vs persistent flags parse, how Args validators and
// RunE propagate errors, and how it contrasts with the single-command stdlib
// `flag` package.
//
// This is the GROUND TRUTH for CLI_COBRA.md. Every captured line and error below
// is produced by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM: every section calls execute(builder, args), which builds a FRESH
// root each time (no cross-section flag state), points SetOut/SetErr at a buffer,
// sets the args, silences cobra's auto error/usage printing, and runs Execute.
// Handlers write via cmd.OutOrStdout() (which walks up to the root's outWriter),
// so all output lands in the buffer deterministically. No os.Args, no terminal,
// no time.Now(), no RNG.
//
// Run:
//
//	go run cli_cobra.go

package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"strings"

	"github.com/spf13/cobra"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

// appVersion is the version the `version` subcommand prints. A real app injects
// this at link time via -ldflags "-X main.appVersion=v1.2.3" (see BUILD_LDFLAGS_GENERATE);
// here it is a const so the captured output is byte-stable across runs.
const appVersion = "v0.1.0"

// errRiskyFailed is the sentinel the `boom` subcommand's RunE returns, so section E
// can assert errors.Is on the exact error that propagates out of Execute.
var errRiskyFailed = errors.New("risky operation failed")

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// findSub returns the child of root named name (looked up on a freshly built,
// never-executed tree, so Commands() contains only the AddCommand'd children).
func findSub(root *cobra.Command, name string) *cobra.Command {
	for _, c := range root.Commands() {
		if c.Name() == name {
			return c
		}
	}
	return nil
}

// execute is the deterministic driver. build() returns a FRESH root each call;
// we point SetOut+SetErr at a buffer (so nothing escapes to the real terminal),
// set the argv cobra dispatches on, silence cobra's auto error/usage printing
// (we assert on the returned error from Execute instead), run Execute, and return
// the captured buffer + the Execute error.
func execute(build func() *cobra.Command, args []string) (string, error) {
	root := build()
	var buf bytes.Buffer
	root.SetOut(&buf) // outWriter; OutOrStdout()/Println walk up to this on children
	root.SetErr(&buf) // errWriter too, so usage/error never hits real stderr
	root.SetArgs(args)
	root.SilenceUsage = true  // don't dump usage on error (we assert on the error)
	root.SilenceErrors = true // don't print "Error: ..." (we assert on the error)
	err := root.Execute()
	return buf.String(), err
}

// newAppRoot builds the canonical demo command tree used by every section.
// A FRESH tree is built per execute() call so flag state never leaks between
// sections. The tree:
//
//	app                         (no Run -> requires a subcommand)
//	|-- persistent --verbose/-v (inherited by EVERY child)
//	|-- hello                   (prints a fixed greeting)
//	|-- version                 (prints appVersion)
//	|-- greet                   (local --name/--count flags)
//	|-- shout [msg]             (local --mode; reads inherited --verbose)
//	|-- whisper                 (sibling without --mode)
//	|-- echo [msg]              (Args: cobra.ExactArgs(1))
//	|-- quiet                   (Args: cobra.NoArgs)
//	|-- multi ...               (Args: cobra.MinimumNArgs(2))
//	`-- boom                    (RunE returns errRiskyFailed)
func newAppRoot() *cobra.Command {
	root := &cobra.Command{
		Use:   "app",
		Short: "demo CLI",
	}
	// Persistent flag: parsed by EVERY descendant, not just root.
	root.PersistentFlags().BoolP("verbose", "v", false, "verbose output")

	hello := &cobra.Command{
		Use:   "hello",
		Short: "say hello",
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Fprintln(cmd.OutOrStdout(), "hello, world")
		},
	}
	version := &cobra.Command{
		Use:   "version",
		Short: "print version",
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Fprintf(cmd.OutOrStdout(), "app version %s\n", appVersion)
		},
	}

	// greet: LOCAL flags --name/--count (scoped to greet only).
	var gName string
	var gCount int
	greet := &cobra.Command{
		Use:   "greet",
		Short: "greet someone",
		Run: func(cmd *cobra.Command, args []string) {
			for i := 0; i < gCount; i++ {
				fmt.Fprintf(cmd.OutOrStdout(), "hello, %s\n", gName)
			}
		},
	}
	greet.Flags().StringVar(&gName, "name", "world", "name to greet")
	greet.Flags().IntVar(&gCount, "count", 1, "number of times to greet")

	// shout: a LOCAL --mode flag, plus it READS the inherited --verbose.
	var mode string
	shout := &cobra.Command{
		Use:   "shout [msg]",
		Short: "shout a message",
		Run: func(cmd *cobra.Command, args []string) {
			verbose, _ := cmd.Flags().GetBool("verbose") // inherited persistent flag
			msg := strings.Join(args, " ")
			if mode == "upper" {
				msg = strings.ToUpper(msg)
			}
			if verbose {
				fmt.Fprintf(cmd.OutOrStdout(), "[verbose] %s\n", msg)
				return
			}
			fmt.Fprintln(cmd.OutOrStdout(), msg)
		},
	}
	shout.Flags().StringVar(&mode, "mode", "plain", "output mode: plain|upper")

	whisper := &cobra.Command{
		Use:   "whisper",
		Short: "whisper (sibling without --mode)",
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Fprintln(cmd.OutOrStdout(), "...")
		},
	}

	// echo: positional-arg validation via cobra.ExactArgs(1).
	echo := &cobra.Command{
		Use:   "echo [msg]",
		Short: "echo exactly one arg",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Fprintf(cmd.OutOrStdout(), "you said: %s\n", args[0])
		},
	}
	quiet := &cobra.Command{
		Use:   "quiet",
		Short: "takes no positional args",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Fprintln(cmd.OutOrStdout(), "quiet")
		},
	}
	multi := &cobra.Command{
		Use:   "multi [args...]",
		Short: "needs at least 2 positional args",
		Args:  cobra.MinimumNArgs(2),
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Fprintf(cmd.OutOrStdout(), "got %d args\n", len(args))
		},
	}

	// boom: RunE returns an error; Execute propagates it (section E).
	boom := &cobra.Command{
		Use:   "boom",
		Short: "always fails (RunE returns an error)",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Fprintln(cmd.OutOrStdout(), "starting risky op")
			return errRiskyFailed
		},
	}

	root.AddCommand(hello, version, greet, shout, whisper, echo, quiet, multi, boom)
	return root
}

// sectionA shows the command TREE: a root with AddCommand(sub...); Execute
// dispatches by the FIRST arg to the matching subcommand's Run.
func sectionA() {
	sectionBanner("A — Root + subcommands: dispatch by the first arg")

	out, err := execute(newAppRoot, []string{"hello"})
	fmt.Printf("SetArgs([\"hello\"])   -> Execute error: %v\n", err)
	fmt.Printf("captured:\n%s", out)

	out2, err2 := execute(newAppRoot, []string{"version"})
	fmt.Printf("SetArgs([\"version\"]) -> Execute error: %v\n", err2)
	fmt.Printf("captured:\n%s", out2)

	check(`SetArgs(["hello"]) captured "hello, world"`, strings.Contains(out, "hello, world"))
	check(`SetArgs(["version"]) captured "app version v0.1.0"`, strings.Contains(out2, "app version v0.1.0"))
	check("both dispatches returned nil error", err == nil && err2 == nil)
}

// sectionB shows LOCAL flags: --name (string, default "world") and --count (int)
// are parsed automatically before Run runs. Defaults apply when the flag is absent.
func sectionB() {
	sectionBanner("B — Local flags: --name (string) and --count (int) with defaults")

	outDef, _ := execute(newAppRoot, []string{"greet"})
	fmt.Printf("SetArgs([\"greet\"]) (defaults) -> captured:\n%s", outDef)

	out, err := execute(newAppRoot, []string{"greet", "--name", "Al", "--count", "3"})
	fmt.Printf("SetArgs([\"greet\",\"--name\",\"Al\",\"--count\",\"3\"]) -> Execute error: %v\n", err)
	fmt.Printf("captured:\n%s", out)

	check(`greet output contains "Al"`, strings.Contains(out, "Al"))
	check("greet printed exactly count=3 lines", strings.Count(out, "\n") == 3)
	check(`default name is "world" (1 line)`,
		strings.Contains(outDef, "hello, world") && strings.Count(outDef, "\n") == 1)
	check("Execute returned nil", err == nil)
}

// sectionC contrasts PERSISTENT vs LOCAL flags. A persistent --verbose on root is
// INHERITED by every child (its flag is parsed by descendants); a local --mode on
// `shout` does NOT leak to the sibling `whisper`.
func sectionC() {
	sectionBanner("C — Persistent flags inherit to children; local flags do not leak")

	// Inspect the STATIC tree (built, not executed). InheritedFlags()/LocalFlags()
	// each call mergePersistentFlags() internally, so the inherited --verbose is
	// visible on a child even before Execute; Flags() alone does NOT merge, which
	// is why we use the explicit Inherited/Local views here.
	root := newAppRoot()
	shout := findSub(root, "shout")
	whisper := findSub(root, "whisper")

	shoutInhVerbose := shout.InheritedFlags().Lookup("verbose") != nil // inherited from root
	shoutLocVerbose := shout.LocalFlags().Lookup("verbose") != nil     // NOT local to shout
	whisperInhVerbose := whisper.InheritedFlags().Lookup("verbose") != nil
	whisperLocMode := whisper.LocalFlags().Lookup("mode") != nil // local to shout; no leak

	fmt.Printf("shout   InheritedFlags().Lookup(\"verbose\") != nil? %v   (inherited persistent)\n", shoutInhVerbose)
	fmt.Printf("shout   LocalFlags().Lookup(\"verbose\")    != nil? %v   (NOT local to shout)\n", shoutLocVerbose)
	fmt.Printf("whisper InheritedFlags().Lookup(\"verbose\") != nil? %v   (inherited persistent)\n", whisperInhVerbose)
	fmt.Printf("whisper LocalFlags().Lookup(\"mode\")       != nil? %v   (local to shout; no leak)\n", whisperLocMode)

	// Runtime: shout reads the inherited --verbose AND uses its local --mode.
	out, err := execute(newAppRoot, []string{"shout", "--verbose", "--mode", "upper", "hi there"})
	fmt.Printf("SetArgs([\"shout\",\"--verbose\",\"--mode\",\"upper\",\"hi there\"]) -> Execute error: %v\n", err)
	fmt.Printf("captured:\n%s", out)

	check("child (shout) inherits --verbose (InheritedFlags non-nil)", shoutInhVerbose)
	check("--verbose is NOT a local flag of shout (LocalFlags nil)", !shoutLocVerbose)
	check("sibling (whisper) also inherits --verbose", whisperInhVerbose)
	check("local --mode does NOT leak to sibling (whisper LocalFlags nil)", !whisperLocMode)
	check(`shout output reflects --verbose + --mode=upper ("[verbose] HI THERE")`,
		strings.Contains(out, "[verbose] HI THERE"))
	check("shout Execute returned nil", err == nil)
}

// sectionD shows Args validators: cobra.ExactArgs(1), cobra.NoArgs, and
// cobra.MinimumNArgs(2). A violated validator makes Execute return a non-nil
// error (Run never runs). The error strings are deterministic.
func sectionD() {
	sectionBanner("D — Args validators: ExactArgs(1), NoArgs, MinimumNArgs(2)")

	// echo has ExactArgs(1): 2 positional args -> error; 1 arg -> ok.
	_, errTwo := execute(newAppRoot, []string{"echo", "a", "b"})
	outOne, errOne := execute(newAppRoot, []string{"echo", "only"})
	fmt.Printf("echo (ExactArgs(1)) with [\"a\",\"b\"] -> Execute error:\n  %v\n", errTwo)
	fmt.Printf("echo (ExactArgs(1)) with [\"only\"]   -> Execute error: %v\n", errOne)
	fmt.Printf("captured:\n%s", outOne)

	// quiet has NoArgs: one extra arg -> error.
	_, errNo := execute(newAppRoot, []string{"quiet", "extra"})
	fmt.Printf("quiet (NoArgs) with [\"extra\"]       -> Execute error:\n  %v\n", errNo)

	// multi has MinimumNArgs(2): one arg -> error.
	_, errMin := execute(newAppRoot, []string{"multi", "only-one"})
	fmt.Printf("multi (MinimumNArgs(2)) with [\"only-one\"] -> Execute error:\n  %v\n", errMin)

	check("ExactArgs(1) with 2 args -> Execute returns non-nil error", errTwo != nil)
	check(`error message == "accepts 1 arg(s), received 2"`,
		errTwo != nil && errTwo.Error() == "accepts 1 arg(s), received 2")
	check("ExactArgs(1) with 1 arg -> Execute returns nil", errOne == nil)
	check("NoArgs with 1 arg -> Execute returns non-nil error", errNo != nil)
	check(`NoArgs error contains "unknown command"`, strings.Contains(errNo.Error(), "unknown command"))
	check("MinimumNArgs(2) with 1 arg -> Execute returns non-nil error", errMin != nil)
	check(`MinimumNArgs(2) error == "requires at least 2 arg(s), only received 1"`,
		errMin != nil && errMin.Error() == "requires at least 2 arg(s), only received 1")
}

// sectionE shows RunE (returns error) vs Run (no error). When RunE returns a
// non-nil error, Execute returns that exact error to the caller (here asserted
// with errors.Is). Run cannot do this — prefer RunE for error propagation.
func sectionE() {
	sectionBanner("E — RunE (returns error) vs Run: Execute propagates the error")

	out, err := execute(newAppRoot, []string{"boom"})
	fmt.Printf("SetArgs([\"boom\"]) -> Execute error: %v\n", err)
	fmt.Printf("handler captured before returning:\n%s", out)

	check("RunE error propagates out of Execute (non-nil)", err != nil)
	check("Execute returned the exact sentinel (errors.Is)", errors.Is(err, errRiskyFailed))
	check(`handler ran before failing (captured "starting risky op")`,
		strings.Contains(out, "starting risky op"))
}

// stdlibDispatch is what you MUST write by hand with the stdlib `flag` package to
// get subcommand dispatch: a switch on the first arg, a fresh FlagSet per
// command, and a hand-rolled "unknown command" default. cobra gives you all of
// this for free (the tree, the dispatch, the suggestions, the help).
func stdlibDispatch(sub string, rest []string, w io.Writer) error {
	switch sub {
	case "greet":
		fs := flag.NewFlagSet("greet", flag.ContinueOnError) // ContinueOnError -> return, not os.Exit
		fs.SetOutput(w)                                      // analog of cobra SetOut: usage/errors
		name := fs.String("name", "world", "name to greet")
		count := fs.Int("count", 1, "number of times to greet")
		if err := fs.Parse(rest); err != nil {
			return err
		}
		for i := 0; i < *count; i++ {
			fmt.Fprintf(w, "hello, %s\n", *name)
		}
		return nil
	case "version":
		fmt.Fprintf(w, "stdlib-app version %s\n", appVersion)
		return nil
	default:
		// YOU write this default case; cobra emits "unknown command" for free.
		return fmt.Errorf("unknown command: %q", sub)
	}
}

// sectionF contrasts cobra with the stdlib `flag` package. flag is single-command
// and flat (no tree, no AddCommand); you hand-write the dispatch switch. The same
// greet behavior produces byte-identical output in both.
func sectionF() {
	sectionBanner("F — Contrast: stdlib flag has no command tree (you write dispatch)")

	// 1) cobra greet (fresh tree).
	cobraOut, _ := execute(newAppRoot, []string{"greet", "--name", "Al", "--count", "3"})

	// 2) stdlib flag: hand-rolled dispatch switch (what cobra gives you for free).
	var stdBuf bytes.Buffer
	_ = stdlibDispatch("greet", []string{"--name", "Al", "--count", "3"}, &stdBuf)
	stdOut := stdBuf.String()

	fmt.Printf("cobra  greet -> %d lines:\n%s", strings.Count(cobraOut, "\n"), cobraOut)
	fmt.Printf("stdlib greet -> %d lines:\n%s", strings.Count(stdOut, "\n"), stdOut)
	fmt.Printf("byte-identical? %v\n", cobraOut == stdOut)

	// 3) unknown subcommand: BOTH return an error — but cobra gives it for free.
	_, cobraUnknownErr := execute(newAppRoot, []string{"bogus"})
	var stdBuf2 bytes.Buffer
	stdUnknownErr := stdlibDispatch("bogus", nil, &stdBuf2)
	fmt.Printf("cobra  unknown \"bogus\" -> error: %v   (free)\n", cobraUnknownErr)
	fmt.Printf("stdlib unknown \"bogus\" -> error: %v   (you wrote the switch default)\n", stdUnknownErr)

	check("cobra greet == stdlib greet (byte-identical output)", cobraOut == stdOut)
	check("cobra greet produced exactly 3 lines", strings.Count(cobraOut, "\n") == 3)
	check("cobra unknown subcommand -> Execute error (free)", cobraUnknownErr != nil)
	check("stdlib manual dispatch also errors on unknown", stdUnknownErr != nil)
}

func main() {
	fmt.Println("cli_cobra.go — Phase 7 bundle.")
	fmt.Println("Every line below is produced by driving cobra programmatically via")
	fmt.Println("root.SetArgs + root.SetOut + root.Execute (no os.Args, no terminal).")
	fmt.Println("The .md guide pastes it verbatim. Determinism: a fresh root per run;")
	fmt.Println("handlers write to the captured buffer; errors are asserted, not printed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
