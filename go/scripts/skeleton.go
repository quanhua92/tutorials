//go:build ignore

// __STEM__.go — bundle.
//
// GOAL (one line): TODO.
//
// This is the GROUND TRUTH for __STEM_UPPER__.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     go run __STEM__.go

package main

import (
	"fmt"
	"strings"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// TODO: sectionA, sectionB, ... each prints a banner + a readable block + checks.

func main() {
	fmt.Println("__STEM__.go — bundle.")
	fmt.Println("Every value below is computed by this file.")
	// sectionA()
	sectionBanner("DONE — all sections printed")
}
