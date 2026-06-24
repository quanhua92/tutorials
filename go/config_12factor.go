//go:build ignore

// config_12factor.go — Phase 8 bundle #48.
//
// GOAL (one line): show, by printing every behavior, how a 12-factor app loads
// CONFIG FROM THE ENVIRONMENT: os.LookupEnv disambiguating unset vs empty, a
// typed Config struct parsed from env (with defaults + validation), the
// flag > env > default precedence, required keys failing loudly, and a sorted
// os.Environ() dump — while keeping the bundle deterministic.
//
// This is the GROUND TRUTH for CONFIG_12FACTOR.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// DETERMINISM: reading config from the REAL environment would make output
// machine-dependent. This file avoids that three ways:
//  1. loadConfig takes an EXPLICIT map[string]string (not os.Getenv) so sections
//     B and C are pure functions of a fixed input.
//  2. Sections A and E DO touch the process env (to demonstrate os.Getenv /
//     os.LookupEnv / os.Environ for real), but only via keys with a unique
//     CFG12F_ prefix, set with os.Setenv and restored by a deferred cleanup.
//  3. Section E filters os.Environ() down to that unique prefix, so the printed
//     listing NEVER depends on the host's real environment. Keys are sorted.
// No time.Now() and no RNG value is printed; two `just out` runs are
// byte-identical.
//
// Run:
//
//	go run config_12factor.go

package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

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

// --- defaults for the typed Config (12-factor: sane defaults, overridden by env) -

const (
	defaultPort     = 8080
	defaultMaxConns = 100
	defaultTimeout  = 10 * time.Second
	defaultDebug    = false
)

// Config is a typed configuration struct: every field has a concrete type, so
// downstream code never re-parses a string. loadConfig populates it from env.
type Config struct {
	Port        int           // APP_PORT      (int),      default 8080
	Debug       bool          // APP_DEBUG     (bool),     default false
	Timeout     time.Duration // APP_TIMEOUT   (duration), default 10s
	MaxConns    int           // APP_MAX_CONNS (int),      default 100
	DatabaseURL string        // APP_DATABASE_URL (string), REQUIRED
}

// --- env accessors over an explicit map (deterministic; same shape as os.LookupEnv) -

// envInt returns the parsed int for key, or def when the key is unset. A present
// but unparseable value is an error (fail loudly; never silently default a
// malformed value). The error wraps strconv's error so errors.Is unwraps it.
func envInt(env map[string]string, key string, def int) (int, error) {
	raw, ok := env[key]
	if !ok {
		return def, nil
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("env %s: parse %q: %w", key, raw, err)
	}
	return v, nil
}

// envBool parses APP_x with strconv.ParseBool semantics ("1","t","true",...).
func envBool(env map[string]string, key string, def bool) (bool, error) {
	raw, ok := env[key]
	if !ok {
		return def, nil
	}
	v, err := strconv.ParseBool(raw)
	if err != nil {
		return false, fmt.Errorf("env %s: parse %q: %w", key, raw, err)
	}
	return v, nil
}

// envDuration parses a Go duration string ("30s", "1h30m", ...) via ParseDuration.
func envDuration(env map[string]string, key string, def time.Duration) (time.Duration, error) {
	raw, ok := env[key]
	if !ok {
		return def, nil
	}
	v, err := time.ParseDuration(raw)
	if err != nil {
		return 0, fmt.Errorf("env %s: parse %q: %w", key, raw, err)
	}
	return v, nil
}

// envRequired returns the value of a REQUIRED key. A key that is SET (even to "")
// satisfies "required"; only a genuinely UNSET key is an error. This mirrors
// os.LookupEnv's (value, ok) distinction: "set but empty" is a deliberate
// value, "unset" is a missing dependency.
func envRequired(env map[string]string, key string) (string, error) {
	if raw, ok := env[key]; ok {
		return raw, nil
	}
	return "", fmt.Errorf("env %s: required key is not set", key)
}

// loadConfig is the 12-factor config loader: read each key via the (value, ok)
// lookup, apply a default when unset, parse into the typed field, validate, and
// COLLECT every error (a single bad value does not hide a missing required key).
func loadConfig(env map[string]string) (Config, error) {
	var cfg Config
	var errs []error
	var err error

	if cfg.Port, err = envInt(env, "APP_PORT", defaultPort); err != nil {
		errs = append(errs, err)
	}
	if cfg.Debug, err = envBool(env, "APP_DEBUG", defaultDebug); err != nil {
		errs = append(errs, err)
	}
	if cfg.Timeout, err = envDuration(env, "APP_TIMEOUT", defaultTimeout); err != nil {
		errs = append(errs, err)
	}
	if cfg.MaxConns, err = envInt(env, "APP_MAX_CONNS", defaultMaxConns); err != nil {
		errs = append(errs, err)
	}
	if cfg.DatabaseURL, err = envRequired(env, "APP_DATABASE_URL"); err != nil {
		errs = append(errs, err)
	}
	if len(errs) > 0 {
		return cfg, errors.Join(errs...)
	}
	return cfg, nil
}

// --- precedence: flag > env > default (the common ordering) -------------------

// resolveInt implements the precedence chain: an explicitly-set flag wins; else
// a set env var; else the default. flagChanged is whether the flag was actually
// passed on the command line (flag.FlagSet.Visit only visits SET flags).
func resolveInt(flagVal int, flagChanged bool, envRaw string, envSet bool, def int) int {
	if flagChanged {
		return flagVal
	}
	if envSet {
		if v, err := strconv.Atoi(envRaw); err == nil {
			return v
		}
	}
	return def
}

// parsePortFlag builds a FRESH FlagSet, parses a fixed arg slice (never os.Args),
// and reports the value plus whether "-port" was explicitly set. The FlagSet is
// fresh each call so sections never share flag state.
func parsePortFlag(args []string) (int, bool) {
	fs := flag.NewFlagSet("app", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	p := fs.Int("port", 0, "listen port")
	_ = fs.Parse(args)
	changed := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "port" {
			changed = true
		}
	})
	return *p, changed
}

// --- process-env helpers (deterministic: unique prefix + deferred restore) -----

// setEnvTemp sets key=value and returns a cleanup that restores the prior state
// (re-sets the old value, or unsets if the key did not exist). Used so sections
// can exercise the REAL os.Getenv/os.LookupEnv/os.Environ deterministically.
func setEnvTemp(key, value string) func() {
	prev, ok := os.LookupEnv(key)
	_ = os.Setenv(key, value)
	return func() {
		if ok {
			_ = os.Setenv(key, prev)
		} else {
			_ = os.Unsetenv(key)
		}
	}
}

// ensureUnset removes key for the section and restores any prior value later.
func ensureUnset(key string) func() {
	prev, ok := os.LookupEnv(key)
	_ = os.Unsetenv(key)
	return func() {
		if ok {
			_ = os.Setenv(key, prev)
		}
	}
}

// sectionA proves os.Getenv cannot tell "unset" from "set-to-empty", while
// os.LookupEnv's second return (ok) can. This is THE reason to use LookupEnv.
func sectionA() {
	sectionBanner("A — os.Getenv vs os.LookupEnv (the empty-vs-unset ambiguity)")

	defer setEnvTemp("CFG12F_A_EMPTY", "")() // SET to empty string
	defer ensureUnset("CFG12F_A_MISSING")()  // UNSET

	emptyGet := os.Getenv("CFG12F_A_EMPTY")
	missingGet := os.Getenv("CFG12F_A_MISSING")
	emptyVal, emptyOk := os.LookupEnv("CFG12F_A_EMPTY")
	missingVal, missingOk := os.LookupEnv("CFG12F_A_MISSING")

	fmt.Printf("CFG12F_A_EMPTY  : Getenv=%q  LookupEnv=(%q, ok=%v)   [SET to empty]\n", emptyGet, emptyVal, emptyOk)
	fmt.Printf("CFG12F_A_MISSING: Getenv=%q  LookupEnv=(%q, ok=%v)   [UNSET]\n", missingGet, missingVal, missingOk)
	fmt.Println("-> Getenv returns \"\" in BOTH cases (ambiguous); only LookupEnv's ok distinguishes them.")

	check("Getenv returns empty for set-to-empty", emptyGet == "")
	check("Getenv returns empty for unset (AMBIGUOUS: same as set-to-empty)", missingGet == "" && emptyGet == missingGet)
	check("LookupEnv ok=true for set-to-empty", emptyOk)
	check("LookupEnv ok=false for unset", !missingOk)
}

// sectionB loads a typed Config from a FIXED env map and proves the typed values
// parse correctly (int / bool / duration) and that a missing key falls back to
// its default.
func sectionB() {
	sectionBanner("B — loadConfig: typed struct from a FIXED env map (defaults applied)")

	env := map[string]string{
		"APP_PORT":         "8080",
		"APP_DEBUG":        "true",
		"APP_TIMEOUT":      "30s",
		"APP_DATABASE_URL": "postgres://demo@localhost:5432/app",
		// APP_MAX_CONNS intentionally absent -> default 100 applies.
	}
	cfg, err := loadConfig(env)
	if err != nil {
		panic("unexpected loadConfig error in section B: " + err.Error())
	}
	fmt.Printf("loadConfig(parsed): Port=%d  Debug=%v  Timeout=%v  MaxConns=%d  DatabaseURL=%q\n",
		cfg.Port, cfg.Debug, cfg.Timeout, cfg.MaxConns, cfg.DatabaseURL)
	fmt.Println("APP_MAX_CONNS absent from map -> default 100 applied.")

	check("Port parsed from env as int 8080", cfg.Port == 8080)
	check("Debug parsed from env as bool true", cfg.Debug == true)
	check("Timeout parsed from env as duration 30s", cfg.Timeout == 30*time.Second)
	check("MaxConns defaulted to 100 (key missing)", cfg.MaxConns == 100)
	check("DatabaseURL loaded from required key", cfg.DatabaseURL == "postgres://demo@localhost:5432/app")
}

// sectionC shows validation failing loudly: a required key that is unset returns
// an error (never silently defaulted), and a malformed typed value returns an
// error that wraps strconv.ErrSyntax so callers can match on the cause.
func sectionC() {
	sectionBanner("C — Validation: required-key unset & bad-value -> errors")

	// 1) required key missing.
	_, err := loadConfig(map[string]string{
		"APP_PORT":    "8080",
		"APP_DEBUG":   "false",
		"APP_TIMEOUT": "10s",
		// APP_DATABASE_URL missing -> required error.
	})
	fmt.Printf("required APP_DATABASE_URL missing -> err != nil ? %v\n", err != nil)
	if err != nil {
		fmt.Printf("  error: %v\n", err)
	}

	// 2) bad int value for a typed field.
	_, err2 := loadConfig(map[string]string{
		"APP_PORT":         "not-an-int",
		"APP_DATABASE_URL": "postgres://x",
	})
	fmt.Printf("APP_PORT=%q -> err != nil ? %v\n", "not-an-int", err2 != nil)
	if err2 != nil {
		fmt.Printf("  error: %v\n", err2)
		fmt.Printf("  errors.Is(err, strconv.ErrSyntax) ? %v\n", errors.Is(err2, strconv.ErrSyntax))
	}

	check("required unset -> error returned", err != nil)
	check("bad APP_PORT -> error returned", err2 != nil)
	check("bad APP_PORT error wraps strconv.ErrSyntax", errors.Is(err2, strconv.ErrSyntax))
}

// sectionD proves the precedence chain flag > env > default with the real flag
// package, parsing a fixed arg slice (deterministic; never os.Args).
func sectionD() {
	sectionBanner("D — Precedence: flag > env > default")

	const def = 3000

	// case 1: flag explicitly set -> wins over env and default.
	flagVal1, changed1 := parsePortFlag([]string{"-port", "9090"})
	r1 := resolveInt(flagVal1, changed1, "8080", true, def)

	// case 2: flag absent, env set -> env wins over default.
	flagVal2, changed2 := parsePortFlag(nil)
	r2 := resolveInt(flagVal2, changed2, "8080", true, def)

	// case 3: neither flag nor env -> default.
	flagVal3, changed3 := parsePortFlag(nil)
	r3 := resolveInt(flagVal3, changed3, "", false, def)

	fmt.Printf("case 1 flag=9090(env=8080,default=3000) -> resolved %d  (flag wins)\n", r1)
	fmt.Printf("case 2 flag unset(env=8080,default=3000) -> resolved %d  (env wins)\n", r2)
	fmt.Printf("case 3 flag unset(env unset,default=3000) -> resolved %d  (default wins)\n", r3)

	check("flag overrides env and default -> 9090", r1 == 9090 && changed1)
	check("env overrides default when flag absent -> 8080", r2 == 8080 && !changed2)
	check("default used when neither flag nor env -> 3000", r3 == def && !changed3)
}

// sectionE parses os.Environ() into a map and prints the injected keys, SORTED,
// filtered to the unique CFG12F_DEMO_ prefix so the listing is deterministic.
func sectionE() {
	sectionBanner("E — Parsing os.Environ() into a sorted map (deterministic slice)")

	defer setEnvTemp("CFG12F_DEMO_REGION", "us-west-2")()
	defer setEnvTemp("CFG12F_DEMO_LOG_LEVEL", "info")()

	env := map[string]string{}
	for _, kv := range os.Environ() {
		k, v, ok := strings.Cut(kv, "=")
		if !ok {
			continue
		}
		if strings.HasPrefix(k, "CFG12F_DEMO_") {
			env[k] = v
		}
	}
	keys := make([]string, 0, len(env))
	for k := range env {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	fmt.Println("filtered os.Environ() entries (sorted, CFG12F_DEMO_ only):")
	for _, k := range keys {
		fmt.Printf("  %s=%s\n", k, env[k])
	}

	check("env listing contains CFG12F_DEMO_LOG_LEVEL", env["CFG12F_DEMO_LOG_LEVEL"] == "info")
	check("env listing contains CFG12F_DEMO_REGION", env["CFG12F_DEMO_REGION"] == "us-west-2")
	check("listing is sorted: LOG_LEVEL before REGION", len(keys) == 2 && keys[0] == "CFG12F_DEMO_LOG_LEVEL" && keys[1] == "CFG12F_DEMO_REGION")
}

// sectionF documents the ecosystem choices (envconfig and viper) without
// importing them: the stdlib ordering this bundle implements is flag > env >
// default; the richer libs are shown as code in CONFIG_12FACTOR.md.
func sectionF() {
	sectionBanner("F — Ecosystem: envconfig (tags) & viper (unification) — DOCUMENTED")

	fmt.Println("These third-party libs are DOCUMENTED in CONFIG_12FACTOR.md (not imported here):")
	fmt.Println("  envconfig (kelseyhightower): a struct + `envconfig:\"KEY\"` tag -> typed fields from env.")
	fmt.Println("  viper (spf13): merges defaults < env < config files < flags < Set, with live reload.")

	precedence := []string{"flag", "env", "default"} // the stdlib ordering this bundle implements
	fmt.Printf("stdlib precedence implemented here: %s > %s > %s\n", precedence[0], precedence[1], precedence[2])

	check("stdlib precedence slice is [flag env default]", fmt.Sprintf("%v", precedence) == "[flag env default]")
}

func main() {
	fmt.Println("config_12factor.go — Phase 8 bundle #48.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
