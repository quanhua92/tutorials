// selectors_specificity.js — Phase 1 foundations bundle.
//
// GOAL (one line): print, by computing every value, how a CSS selector earns a
// specificity triplet (a,b,c) = (ID, CLASS, TYPE), how that triplet is compared
// left-to-right (NOT as a base-10 number), and where specificity sits inside the
// cascade (origin -> importance -> specificity -> source order).
//
// This is the GROUND TRUTH for SELECTORS_SPECIFICITY.md. Every number in the
// guide is printed by this file. Change it -> re-run -> re-paste. Never hand-compute.
//
// Run:  node selectors_specificity.js

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

// --- the specificity calculator ------------------------------------------------
// Parse a selector string and return its triplet (a,b,c) = (ID, CLASS, TYPE).
// Handled: type, .class, #id, [attr], :pseudo-class, ::pseudo-element, the
// descendant/child/adjacent combinators, and the universal *.
// Per MDN/web.dev: * and combinators add nothing; functional pseudo-classes
// (:nth-child(...)) skip their parenthesised argument at this level.
function isIdentChar(ch) { return /[A-Za-z0-9_-]/.test(ch); }
function isIdentStart(ch) { return /[A-Za-z*]/.test(ch); }

function specificity(selector) {
  let a = 0, b = 0, c = 0;
  const s = selector;
  const n = s.length;
  let i = 0;
  while (i < n) {
    const ch = s[i];
    // whitespace + combinators -> nothing
    if (ch === " " || ch === "\t" || ch === "\n" || ch === ">" || ch === "+" || ch === "~") {
      i++; continue;
    }
    if (ch === "*") {            // universal selector -> nothing
      i++; continue;
    }
    if (ch === "#") {            // ID selector -> a +1
      i++;
      while (i < n && isIdentChar(s[i])) i++;
      a++; continue;
    }
    if (ch === ".") {            // class selector -> b +1
      i++;
      while (i < n && isIdentChar(s[i])) i++;
      b++; continue;
    }
    if (ch === "[") {            // attribute selector [..] -> b +1
      i++;
      while (i < n && s[i] !== "]") i++;
      if (i < n) i++;            // consume ']'
      b++; continue;
    }
    if (ch === ":") {            // pseudo-class / pseudo-element
      let colons = 0;
      while (i < n && s[i] === ":") { colons++; i++; }
      while (i < n && isIdentChar(s[i])) i++;   // name
      if (s[i] === "(") {                       // functional: skip ( ... )
        let depth = 0;
        while (i < n) {
          if (s[i] === "(") depth++;
          else if (s[i] === ")") { depth--; if (depth === 0) { i++; break; } }
          i++;
        }
      }
      if (colons >= 2) c++;      // ::pseudo-element -> c +1
      else b++;                  // :pseudo-class -> b +1
      continue;
    }
    if (isIdentStart(ch)) {      // type selector -> c +1
      while (i < n && isIdentChar(s[i])) i++;
      c++; continue;
    }
    i++;                         // any other char -> ignore
  }
  return { a, b, c };
}

// Decimal display of the triplet, purely for human readability (NOT base-10 math).
function decimal(t) { return `${t.a}${t.b}${t.c}`; }

// Left-to-right triplet comparison. >0 means s1 wins, <0 means s2 wins, 0 = tie.
function compare(s1, s2) {
  const x = specificity(s1), y = specificity(s2);
  if (x.a !== y.a) return x.a - y.a;
  if (x.b !== y.b) return x.b - y.b;
  return x.c - y.c;
}

// --- Section A: the triplet rules ---------------------------------------------
function section_a() {
  banner("A: the triplet (a,b,c) = (ID, CLASS, TYPE)");
  console.log("  A selector's specificity is a 3-part weight, compared left-to-right:\n");
  console.log("    a  = # of ID selectors           (#id)              +1,0,0");
  console.log("    b  = # of class / attribute / pseudo-class  (.c [a] :pc) +0,1,0");
  console.log("    c  = # of type / pseudo-element   (li  ::pe)         +0,0,1");
  console.log("    *  and combinators ( > + ~ space ) add NOTHING       -> 0,0,0\n");
  console.log("  Atomic facts (each computed by specificity()):");
  const atoms = [
    ["#nav",        1, 0, 0],
    [".item",       0, 1, 0],
    ["a",           0, 0, 1],
    ["*",           0, 0, 0],
    ["[href]",      0, 1, 0],
    [":hover",      0, 1, 0],
    ["::before",    0, 0, 1],
  ];
  for (const [sel, ea, eb, ec] of atoms) {
    const t = specificity(sel);
    check(`"${sel}" -> (${ea},${eb},${ec})`,
      t.a === ea && t.b === eb && t.c === ec);
  }
}

// --- Section B: the worked-examples table -------------------------------------
function section_b() {
  banner("B: worked examples (the specificity table)");
  const rows = [
    ["*",             0, 0, 0],
    ["li",            0, 0, 1],
    ["ul li",         0, 0, 2],
    [".item",         0, 1, 0],
    ["#nav",          1, 0, 0],
    ["#nav .item",    1, 1, 0],
    ["#nav .item a",  1, 1, 1],
    ["a[href]:hover", 0, 2, 1],
    ["#a #b #c",      3, 0, 0],
    [".x.y.z",        0, 3, 0],
    ["div::after",    0, 0, 2],
    [":nth-child(2n)", 0, 1, 0],
  ];
  // column widths
  const wSel = Math.max(...rows.map(r => r[0].length), 18);
  const header = "  " + "selector".padEnd(wSel) + "(a,b,c)" + " ".repeat(8) + "decimal";
  console.log(header);
  console.log("  " + "-".repeat(header.length - 2));
  for (const [sel, ea, eb, ec] of rows) {
    const t = specificity(sel);
    const trip = `(${t.a},${t.b},${t.c})`;
    const expect = `(${ea},${eb},${ec})`;
    console.log("  " + sel.padEnd(wSel) + trip.padEnd(15) + decimal(t));
    check(`"${sel}" == ${expect}`, t.a === ea && t.b === eb && t.c === ec);
  }
  // the pinned GOLD value, asserted explicitly (the .html recomputes this same selector)
  const gold = specificity("#nav .item a");
  check('GOLD "#nav .item a" -> (1,1,1) decimal 111',
    gold.a === 1 && gold.b === 1 && gold.c === 1 && decimal(gold) === "111");
}

// --- Section C: the cascade order ---------------------------------------------
function section_c() {
  banner("C: the cascade (origin -> importance -> specificity -> source order)");
  console.log("  When several rules set the same property on one element, the browser");
  console.log("  picks the winner through this fixed chain (first match wins):\n");
  console.log("    1. ORIGIN & IMPORTANCE   author-normal < author-!important < ...");
  console.log("       (!important is a separate ORIGIN, not a specificity boost)");
  console.log("    2. SPECIFICITY            the (a,b,c) triplet, compared left-to-right");
  console.log("    3. SOURCE ORDER           last-declared rule wins on a tie\n");
  console.log("  Specificity is only compared BETWEEN rules of the same origin/importance.\n");

  // the killer gotcha, demonstrated by computation: a single class beats many types.
  const tenTypes = "html body main article section nav div ul li a"; // 10 type selectors
  const tt = specificity(tenTypes);
  check(`"${tenTypes}" -> (0,0,10)  [10 types, still 0 in CLASS]`,
    tt.a === 0 && tt.b === 0 && tt.c === 10);
  check(`".item" (0,1,0) BEATS "${tenTypes.trim()}" (0,0,10)  [CLASS col > TYPE col]`,
    compare(".item", tenTypes) > 0);

  // IDs dominate regardless of class count
  check(`"#nav" (1,0,0) BEATS ".a.b.c.d.e" (0,5,0)  [ID col > CLASS col]`,
    compare("#nav", ".a.b.c.d.e") > 0);

  // a tie -> equal specificity -> source order decides
  check(`"ul li" (0,0,2) TIES "ol li" (0,0,2)  [-> last-declared wins]`,
    compare("ul li", "ol li") === 0);

  // inline style and !important live OUTSIDE the triplet
  console.log("\n  Two override mechanisms are NOT specificity (they sit higher):");
  console.log("    inline style   -> think (1,0,0,0); beats every author selector");
  console.log("    !important     -> moves the declaration to a higher ORIGIN;");
  console.log("                     only another !important (or higher) can beat it.");
}

console.log("selectors_specificity.js — Phase 1 bundle. Every value below is computed by this file.\n");
section_a();
section_b();
section_c();
banner("DONE — all sections printed");
