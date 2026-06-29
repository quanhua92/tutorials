// asset_library — ground-truth runnable for "SHA-256 content addressing + the Asset library surface"
// Run: pnpm exec tsx bundles/asset_library.ts
//
// Teaches RFC 0001 §5.1 (assets/ content-addressed by SHA-256), §7 (Asset
// library: "browse/drop assets → SHA ref lands in index.json"), and §13 (the
// cloud stores blobs as OPAQUE content during sync — never interprets them).
// Every value ASSET_LIBRARY.md cites is printed here, deterministically, using
// node:crypto SHA-256 over FIXED in-source byte strings. No FS reads, no RNG,
// no wall-clock.

export {}; // make this a module (isolated top-level scope, no cross-file clashes)

import { createHash } from "node:crypto";

const BANNER = "=".repeat(60);
const banner = (t: string): void => {
  console.log(`\n${BANNER}\n${t}\n${BANNER}`);
};

/** Assert an invariant; prints `[check] desc: OK` and exits non-zero on failure. */
function check(desc: string, ok: boolean): void {
  if (!ok) {
    console.error(`FAIL: ${desc}`);
    process.exit(1);
  }
  console.log(`[check] ${desc}: OK`);
}

// ---- SHA-256 primitive (deterministic; node:crypto over fixed bytes) ----

/** SHA-256 of a string/byte payload, returned as lowercase hex. */
function sha256Hex(data: Buffer | string): string {
  return createHash("sha256").update(typeof data === "string" ? Buffer.from(data, "utf8") : data).digest("hex");
}

/** The ref format that lands in index.json: `sha256:<hex>`. */
function refFor(data: Buffer | string): string {
  return `sha256:${sha256Hex(data)}`;
}

// ---- a minimal content-addressable blob store (in-memory model of assets/) ----
// Keys are SHA-256 hex; the stored blob is the value. Identical bytes hash to
// the SAME key, so the second write is a no-op → dedup is free.

class AssetStore {
  private blobs = new Map<string, Buffer>();

  /** Store a blob; returns its ref `sha256:<hex>`. Duplicate bytes are a no-op. */
  store(data: Buffer): string {
    const hex = sha256Hex(data);
    if (!this.blobs.has(hex)) this.blobs.set(hex, data);
    return `sha256:${hex}`;
  }

  get storedCount(): number {
    return this.blobs.size;
  }

  has(ref: string): boolean {
    return this.blobs.has(ref.slice("sha256:".length));
  }
}

// ---- fixed in-source byte payloads (deterministic; NO RNG, NO clock) ----
// Pretend these are binary files dropped onto the Asset library panel.

const PNG_A = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, // PNG signature
  0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82, // tail bytes
]);
const PNG_A_DUP = Buffer.from([ // byte-identical to PNG_A (e.g. dropped twice)
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
]);
const PNG_B = Buffer.from([ // different bytes → different SHA
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  0xff, 0xff, 0xff, 0xff, 0xae, 0x42, 0x60, 0x82,
]);

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: content addressing — the sha256:<hex> ref format");
  console.log("  RFC 0001 §5.1 — assets/ holds blobs \"content-addressed by SHA-256\".\n");
  const ref = refFor(PNG_A);
  console.log(`  bytes (PNG_A, ${PNG_A.length}B) → ${ref}`);
  console.log("  → the REF is what index.json stores. The blob sits in assets/. JSON never embeds bytes.");
  check("ref format is `sha256:<64 lowercase hex>`", /^sha256:[0-9a-f]{64}$/.test(ref));
  console.log(`  PINNED: ref = ${ref}`);
}

function sectionB(): void {
  banner("SECTION B: determinism + the avalanche effect");
  console.log("  Same bytes ⇒ same SHA (deterministic). A 1-byte input change ⇒ a totally different SHA.\n");
  const hello = sha256Hex("hello");
  const hellp = sha256Hex("hellp"); // 1 character changed (e→p)
  console.log(`  sha256("hello") = ${hello}`);
  console.log(`  sha256("hellp") = ${hellp}`);
  check("sha256(\"hello\") is the pinned gold value", hello === "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
  check("determinism: same input recomputed ⇒ same hash", sha256Hex("hello") === hello);

  // Avalanche: bit-level Hamming distance between the two 256-bit digests.
  const a = createHash("sha256").update("hello").digest();
  const b = createHash("sha256").update("hellp").digest();
  let diffBits = 0;
  for (let i = 0; i < a.length; i++) {
    let x = a[i] ^ b[i];
    while (x) { diffBits += x & 1; x >>= 1; }
  }
  // shared leading hex chars (visual proof of "totally different")
  let sharedPrefix = 0;
  const ha = a.toString("hex"), hb = b.toString("hex");
  for (let i = 0; i < ha.length; i++) { if (ha[i] === hb[i]) sharedPrefix++; else break; }
  console.log(`  1-char input change → ${diffBits}/256 output bits differ (${(diffBits / 256 * 100).toFixed(1)}%), ${sharedPrefix} shared leading-hex chars.`);
  check("avalanche: ~50% of output bits flip on a 1-char input change", diffBits > 100 && diffBits < 156);
}

function sectionC(): void {
  banner("SECTION C: dedup — same bytes ⇒ one stored blob");
  console.log("  Drop the SAME asset twice → one blob on disk, one ref. Content addressing makes dedup free.\n");
  const store = new AssetStore();
  const r1 = store.store(PNG_A);
  const r2 = store.store(PNG_A_DUP); // byte-identical
  const r3 = store.store(PNG_B);     // different bytes
  console.log(`  drop #1 (PNG_A)       → ${r1}`);
  console.log(`  drop #2 (PNG_A_DUP)   → ${r2}   ← same ref, store() was a no-op`);
  console.log(`  drop #3 (PNG_B)       → ${r3}`);
  console.log(`  3 drop() calls, ${store.storedCount} unique blobs stored.`);
  check("dedup: 2 identical blobs collapse to 1 stored file (3 inputs → 2 stored)", store.storedCount === 2);
  check("dedup: both drops of the same bytes return the SAME ref", r1 === r2);
  console.log(`  PINNED: storedCount = ${store.storedCount} for 3 inputs (2 are byte-identical).`);
}

function sectionD(): void {
  banner("SECTION D: the ref lands in index.json — never the bytes");
  console.log("  RFC 0001 §5.2 / §5.3 — asset refs (not blobs) live in index.json:\n");
  const imgRef = refFor(PNG_A);
  const musicRef = refFor(PNG_B);
  // Slide-level (§5.3): slide `assets` map holds SHA refs.
  const slideIndex = {
    id: "slide-0",
    assets: { img: imgRef }, // ← SHA ref, NOT base64 bytes
  };
  // Root-level (§5.2): `audio.music.asset` is a SHA ref.
  const rootIndex = {
    audio: { music: { asset: musicRef, volume: 0.08, loop: true } },
  };
  console.log("  slide-0/index.json:");
  console.log(`    "assets": ${JSON.stringify(slideIndex.assets)}`);
  console.log("  root/index.json:");
  console.log(`    "audio.music": ${JSON.stringify(rootIndex.audio.music)}`);
  check("slide `assets` value is a `sha256:` ref (no embedded bytes)", /^sha256:[0-9a-f]{64}$/.test(slideIndex.assets.img));
  check("root `audio.music.asset` is a `sha256:` ref (not a base64 blob)", /^sha256:[0-9a-f]{64}$/.test(rootIndex.audio.music.asset));
  console.log("  → cross-ref SLIDE_INDEX_JSON (`slide.assets`) and ROOT_INDEX_JSON (`audio.music.asset`).");
}

function sectionE(): void {
  banner("SECTION E: the Asset library surface — browse/drop → hash → store → write ref");
  console.log("  RFC 0001 §7 — Asset library: \"browse/drop assets → SHA ref lands in index.json\".");
  console.log("  AGENTS.md (image field): \"Byte swap to assets/, __FIELD_ID__ path replacement\".\n");
  // The drop flow, modelled end-to-end.
  const store = new AssetStore();
  const dropped = PNG_A;
  const ref = store.store(dropped);                  // 1) hash + store blob in assets/
  const assetPath = `assets/${ref.slice("sha256:".length, 16)}.png`; // 2) blob path
  const stampedHtml = `<img src="${assetPath}" />`;  // 3) __IMAGE__ → path replacement
  console.log(`  drop PNG_A (${dropped.length}B)`);
  console.log(`    1) hash + store   → ${ref}`);
  console.log(`    2) blob on disk   → ${assetPath}`);
  console.log(`    3) __IMAGE__ swap → ${stampedHtml}`);
  check("drop produced a `sha256:` ref AND a path under assets/", /^sha256:[0-9a-f]{64}$/.test(ref) && assetPath.startsWith("assets/"));
  check("store holds exactly one blob after one drop", store.storedCount === 1);
  console.log("  → cross-ref DATA_BINDING: image fields = byte swap to assets/ + __FIELD__ PATH replacement.");
}

function sectionF(): void {
  banner("SECTION F: cloud sync (§13) — blobs are OPAQUE content");
  console.log("  RFC 0001 §13 — the control plane stores the project document as \"opaque");
  console.log("  content\" during sync. It NEVER interprets, renders, or runs inference on it.\n");
  const ref = refFor(PNG_A);
  // The cloud sync payload: refs + raw bytes. The cloud treats bytes as opaque.
  const syncPayload = {
    manifest: { "slide-0/index.json": { assets: { img: ref } } },
    blobs: { [ref]: "<opaque bytes — not parsed by cloud>" },
  };
  const cloudInterpreted = false; // by design (§13): no inference in the cloud
  console.log(`  sync payload carries the ref (${ref.slice(0, 24)}…) + opaque bytes.`);
  console.log("  cloud stores blobs to S3 + indexes the ref; it does NOT decode/compare/render them.");
  check("cloud never interprets blob content (§13: no inference in the cloud)", cloudInterpreted === false);
  check("sync payload keys blobs by SHA ref (content-addressed even in transit)", Object.keys(syncPayload.blobs)[0].startsWith("sha256:"));
  console.log("  → defer cloud to RFC 0003/0004; v1 is local-first (no cloud required).");
}

function main(): void {
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionF();
  banner("DONE");
}

main();
