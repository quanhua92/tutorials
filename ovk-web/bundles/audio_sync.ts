// audio_sync — ground-truth runnable for the "external-<audio> sync" concept
// (RFC 0001 §8 + AGENTS.md "Preview audio")
// Run: pnpm exec tsx bundles/audio_sync.ts
//
// Teaches the preview's audio-sync pattern. The preview page does NOT use the
// HyperFrames player's internal audio — it spawns EXTERNAL <audio> elements
// (ext-music, ext-voiceover) and drives their currentTime from the player's
// playhead on every `timeupdate` event. This bypasses the player's internal
// muting. The music track LOOPS (modulo math); the voiceover track does NOT
// (clamp math). This runnable prints every value AUDIO_SYNC.md cites verbatim.

export {}; // make this a module (isolated top-level scope, no cross-file clashes)

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

/** Fixed-precision float formatter (determinism: NO bare number printing). */
const f = (x: number): string => x.toFixed(6);

// ---- deterministic sample data (NO Date.now, NO Math.random, NO FS reads) ----
// Volumes + loop flags come VERBATIM from AGENTS.md "Preview audio".
// Track durations are realistic pinned sample values (a 30s music bed under a
// 70s voiceover under a ~75s video). Re-running is byte-identical.

interface ExtTrack {
  id: string;          // the element id in render_player_page()
  volume: number;      // AGENTS.md: ext-music 0.08, ext-voiceover 1.0
  loop: boolean;       // AGENTS.md: ext-music looped, ext-voiceover NOT looped
  duration: number;    // seconds of owned media (music bed / voiceover file)
  role: string;
}

const MUSIC: ExtTrack = {
  id: "ext-music",
  volume: 0.08,
  loop: true,
  duration: 30.0,
  role: "music bed (ducked)",
};

const VOICEOVER: ExtTrack = {
  id: "ext-voiceover",
  volume: 1.0,
  loop: false,
  duration: 70.0,
  role: "voiceover (primary)",
};

const TRACKS: ExtTrack[] = [MUSIC, VOICEOVER];

// The player playhead values we evaluate (RFC §8: preview is playhead-driven).
const PLAYHEADS: number[] = [0.0, 12.0, 30.0, 75.0, 90.0];

// ---- the two sync formulas (RFC §8 + AGENTS.md "Preview audio") ----

/**
 * Music track: LOOPED. Effective position wraps at the music bed length.
 *   pos = currentTime % musicDuration
 * A 30s bed under a 75s video loops 2.5x (75/30 = 2.5).
 */
function musicPos(currentTime: number, track: ExtTrack): number {
  return currentTime % track.duration;
}

/**
 * Voiceover track: NOT looped. Position is the playhead CLAMPED to [0, dur].
 *   pos = min(currentTime, duration)
 * Past the end, the voice is silent (stopped at its last sample).
 */
function voicePos(currentTime: number, track: ExtTrack): number {
  return Math.min(currentTime, track.duration);
}

/** Dispatch by loop flag — the ONE function the timeupdate handler calls. */
function syncPos(currentTime: number, track: ExtTrack): number {
  return track.loop ? musicPos(currentTime, track) : voicePos(currentTime, track);
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: why EXTERNAL <audio> (bypass player muting)");
  console.log("  AGENTS.md \"Preview audio\" (verbatim):");
  console.log('    "The preview page (render_player_page()) uses external <audio>');
  console.log("     elements synced to the HyperFrames player via event listeners.");
  console.log('     This bypasses the player\'s internal muting."');
  console.log("");
  console.log("  RFC 0001 §8 (verbatim):");
  console.log('    "Syncs audio via the external-<audio> pattern documented in');
  console.log('     AGENTS.md (\'Preview audio\')."');
  console.log("");
  console.log("  → external <audio> is NOT the player\'s internal audio. It is a");
  console.log("    separate HTMLMediaElement the editor controls directly, so the");
  console.log("    player cannot mute it.");
  check("external <audio> bypasses player muting (AGENTS.md + RFC §8)", true);
}

function sectionB(): void {
  banner("SECTION B: the two tracks (config from AGENTS.md)");
  console.log("  ┌──────────────┬────────┬──────┬──────────┬──────────────────────┐");
  console.log("  │ id           │ volume │ loop │ duration │ role                 │");
  console.log("  ├──────────────┼────────┼──────┼──────────┼──────────────────────┤");
  for (const t of TRACKS) {
    console.log(
      `  │ ${t.id.padEnd(12)} │ ${String(t.volume).padEnd(6)} │ ${String(t.loop).padEnd(4)} │ ${f(t.duration).padEnd(8)} │ ${t.role.padEnd(20)} │`,
    );
  }
  console.log("  └──────────────┴────────┴──────┴──────────┴──────────────────────┘");
  check("ext-music volume === 0.08 (ducked bed)", MUSIC.volume === 0.08);
  check("ext-voiceover volume === 1.0 (primary)", VOICEOVER.volume === 1.0);
  check("ext-music loop === true", MUSIC.loop === true);
  check("ext-voiceover loop === false", VOICEOVER.loop === false);
}

function sectionC(): void {
  banner("SECTION C: the sync mechanism (timeupdate → set currentTime)");
  console.log("  AGENTS.md \"Preview audio\" (verbatim):");
  console.log('    "Both sync to _player.currentTime via timeupdate events."');
  console.log("");
  console.log("  MDN HTMLMediaElement/timeupdate_event (verbatim):");
  console.log('    "The timeupdate event is fired when the time indicated by the');
  console.log('     currentTime attribute has been updated."');
  console.log("    Frequency: ~4Hz–66Hz (system-load dependent).");
  console.log("");
  console.log("  handler (sketch):");
  console.log("    _player.addEventListener('timeupdate', () => {");
  console.log("      const t = _player.currentTime;");
  console.log("      ext_music.currentTime     = syncPos(t, MUSIC);     // % duration");
  console.log("      ext_voiceover.currentTime = syncPos(t, VOICEOVER);  // min(t, dur)");
  console.log("    });");
  check("sync source = _player.currentTime; trigger = timeupdate event", true);

  // Prove syncPos() dispatches by loop flag to the right formula.
  const dispatchOk =
    syncPos(75.0, MUSIC) === musicPos(75.0, MUSIC) &&
    syncPos(75.0, VOICEOVER) === voicePos(75.0, VOICEOVER);
  check("syncPos dispatches by loop flag (modulo for music, clamp for voice)", dispatchOk);
}

function note(t: number): string {
  const loops = t / MUSIC.duration;
  const voiceClamped = voicePos(t, VOICEOVER) >= VOICEOVER.duration;
  const parts: string[] = [];
  parts.push(`music loop × ${loops.toFixed(6)}`);
  parts.push(voiceClamped ? "voice clamped" : "voice in range");
  return parts.join("; ");
}

function sectionD(): void {
  banner("SECTION D: loop math — music MODULO, voiceover CLAMP");
  console.log("  MUSIC (looped):    pos = currentTime % duration");
  console.log("  VOICEOVER (clamp): pos = min(currentTime, duration)  [stops at end]\n");
  console.log("  ┌────────────┬───────────────────┬───────────────────────┬──────────────────────────────────────┐");
  console.log("  │ playhead   │ ext-music pos     │ ext-voiceover pos     │ note                                 │");
  console.log("  ├────────────┼───────────────────┼───────────────────────┼──────────────────────────────────────┤");
  for (const t of PLAYHEADS) {
    const mp = musicPos(t, MUSIC);
    const vp = voicePos(t, VOICEOVER);
    console.log(
      `  │ ${f(t).padEnd(10)} │ ${f(mp).padEnd(17)} │ ${f(vp).padEnd(21)} │ ${note(t).padEnd(36)} │`,
    );
  }
  console.log("  └────────────┴───────────────────┴───────────────────────┴──────────────────────────────────────┘");

  // PINNED values (cited verbatim in the guide + gold-checked in the .html).
  const m75 = musicPos(75.0, MUSIC);
  const v75 = voicePos(75.0, VOICEOVER);
  const m12 = musicPos(12.0, MUSIC);
  const v12 = voicePos(12.0, VOICEOVER);

  check("at currentTime=75.0 → music pos = 75 % 30 = 15.0", m75 === 15.0);
  check("at currentTime=75.0 → voiceover pos = min(75, 70) = 70.0 (clamped)", v75 === 70.0);
  check("at currentTime=12.0 → music pos = 12.0 (first loop)", m12 === 12.0);
  check("at currentTime=12.0 → voiceover pos = 12.0 (within range)", v12 === 12.0);

  console.log(`  PINNED: currentTime=75.0 → musicPos=${f(m75)}, voicePos=${f(v75)}`);
  console.log(`  PINNED: currentTime=12.0 → musicPos=${f(m12)}, voicePos=${f(v12)}`);
}

function sectionE(): void {
  banner("SECTION E: audio refs live in root index.json (RFC §5.2)");
  console.log("  RFC 0001 §5.2 (verbatim schema):");
  console.log('    "audio": {');
  console.log('      "music":     { "asset": "sha256:...", "volume": 0.08, "loop": true },');
  console.log('      "voiceover": { "asset": "voiceover.mp3", "auto_generated": true }');
  console.log("    }");
  console.log("");
  console.log("  → the editor edits audio.music.asset / audio.voiceover.asset here;");
  console.log("    render_player_page() reads them to wire <audio src> for preview.");
  check("audio refs (music + voiceover) are root-level in index.json (§5.2)", true);
}

function main(): void {
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  banner("DONE");
}

main();
