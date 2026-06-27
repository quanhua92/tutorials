// box_model.js — Phase 1 foundations bundle #1 (STYLE ANCHOR).
//
// GOAL (one line): print, by computing every value, how the CSS box model adds
// up content + padding + border + margin, and how `box-sizing` flips what the
// declared `width` means.
//
// This is the GROUND TRUTH for BOX_MODEL.md. Every number in the guide is printed
// by this file. Change it -> re-run -> re-paste. Never hand-compute.
//
// Run:  node box_model.js

const BAR = "=".repeat(70);

function banner(title) {
  console.log(`\n${BAR}\nSECTION ${title}\n${BAR}`);
}

// Assert an invariant and print a uniform [check] ... OK line.
function check(desc, ok) {
  if (!ok) {
    console.error(`INVARIANT VIOLATED: ${desc}`);
    process.exit(1);
  }
  console.log(`[check] ${desc}: OK`);
}

// The box model math. `sizing` is 'content-box' (default) or 'border-box'.
// All edges are symmetric (same value on all 4 sides) for clarity.
function box({ width, padding, border, margin, sizing }) {
  const W = width, P = padding, B = border, M = margin;
  let content, paddingEdge, borderEdge, marginEdge;
  if (sizing === "content-box") {
    content = W;                       // width = content only
    paddingEdge = content + 2 * P;
    borderEdge = paddingEdge + 2 * B;  // == offsetWidth
    marginEdge = borderEdge + 2 * M;
  } else {
    // border-box: width includes content + padding + border
    borderEdge = W;                    // == offsetWidth == declared width
    content = W - 2 * P - 2 * B;
    paddingEdge = content + 2 * P;
    marginEdge = borderEdge + 2 * M;
  }
  return { content, paddingEdge, borderEdge, marginEdge };
}

function section_a() {
  banner("A: the four edges (content-box, the default)");
  const r = box({ width: 200, padding: 20, border: 5, margin: 10, sizing: "content-box" });
  console.log("  width=200  padding=20  border=5  margin=10  box-sizing=content-box\n");
  console.log("  content (width)   = " + r.content);
  console.log("  padding-edge      = " + r.paddingEdge + "   (content + 2*padding)");
  console.log("  border-edge       = " + r.borderEdge + "   (= offsetWidth)");
  console.log("  margin-edge       = " + r.marginEdge + "   (border-edge + 2*margin)");
  check("content-box border-edge == 200 + 40 + 10 == 250", r.borderEdge === 250);
  check("content-box margin-edge == 250 + 20 == 270", r.marginEdge === 270);
}

function section_b() {
  banner("B: box-sizing: border-box (the reset everyone copies)");
  const r = box({ width: 200, padding: 20, border: 5, margin: 10, sizing: "border-box" });
  console.log("  width=200  padding=20  border=5  margin=10  box-sizing=border-box\n");
  console.log("  border-edge (= W)  = " + r.borderEdge + "   (offsetWidth == declared width)");
  console.log("  content           = " + r.content + "   (W - 2*padding - 2*border)");
  console.log("  padding-edge      = " + r.paddingEdge);
  console.log("  margin-edge       = " + r.marginEdge);
  check("border-box offsetWidth == declared width 200", r.borderEdge === 200);
  check("border-box content == 200 - 40 - 10 == 150", r.content === 150);
}

function section_c() {
  banner("C: the headline contrast — same width, different footprint");
  const cb = box({ width: 200, padding: 20, border: 5, margin: 10, sizing: "content-box" });
  const bb = box({ width: 200, padding: 20, border: 5, margin: 10, sizing: "border-box" });
  console.log("  content-box  offsetWidth = " + cb.borderEdge + "   margin-edge = " + cb.marginEdge);
  console.log("  border-box   offsetWidth = " + bb.borderEdge + "   margin-edge = " + bb.marginEdge);
  console.log("  -> same `width:200` spans 50px less horizontally under border-box.");
  check("border-box is 50px narrower than content-box", cb.marginEdge - bb.marginEdge === 50);
}

console.log("box_model.js — Phase 1 style anchor. Every value below is computed by this file.\n");
section_a();
section_b();
section_c();
banner("DONE — all sections printed");
