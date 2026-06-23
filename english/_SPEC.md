# `_SPEC.md` — Coordinator build spec for the `english/` folder

> **Internal coordinator document.** This is the single source of truth that the
> **writer / reviewer / editor** subagents read before touching any doc. It is
> *not* a learner-facing file. The three deliverables (`README.md`,
> `HOW_TO_RESEARCH.md`, `CURRICULUM.md`) are composed by writers as **original
> prose** that *satisfies* this spec — they must not copy this file verbatim.
>
> Sister folders to study for **style** (structure, tone, mermaid use, tables):
> `python/HOW_TO_RESEARCH.md` (the methodology this folder adapts) and
> `python/TODO.md` (the checklist style the Curriculum adapts).

---

## 1. The project in one paragraph

`english/` is an 80/20 English-fluency research repo for a **Vietnamese L1**
learner. The goal: spend **~20 min/day** for **6 months (180 days)** and reach
**"80% native" = confident functional fluency in ~90 high-frequency speaking +
writing scenarios** (produce native-like chunks, be understood without
repetition, switch register, write common professional messages). It is
**speaking- and writing-first**; reading/listening are not the focus. The whole
folder is built by **subagents** (writer → reviewer → editor), never hand-written
by the coordinator.

## 2. The honest definition of "80% native"

State it plainly in the docs — do not overpromise:
- Functional/structural fluency in the high-frequency zones, **not** a flawless
  native accent.
- Can handle ~90 common scenarios fluidly using native-like **chunks** (not
  word-by-word translation).
- Intelligible **without repetition**.
- Switches **register** (casual ↔ professional) and **mode** (speak ↔ write).
- The 20% effort is Pareto: ~2,000 most-frequent spoken word families + ~50
  speech acts + ~10 pronunciation fixes cover ~85–90% of real conversation.

## 3. The mindset (why this works) — README must cover all six

1. **Pareto 20→80** — attack the high-frequency zones; ignore rare features.
2. **Chunks, not words** — fluency = retrieving multi-word patterns, not
   translating word-by-word.
3. **Output only counts** — you only "know" what you can *say* or *write*. Every
   day you produce, not just read.
4. **Real attestation** — every example is a cited real native usage (dictionary
   / corpus / YouGlish). No invented "sounds native to me" sentences.
5. **L1-aware** — every pitfall targets **Vietnamese → English** interference.
6. **Daily dose beats binge** — 20 min/day × 180 days beats cramming.

## 4. The bundle model (the "concept-as-a-bundle" rule, adapted)

> **The one rule:** every example that appears in a `.md` or `.html` is a real,
> **cited** attestation recorded in `{name}_corpus.md`. Nothing invented.

A bundle is a **triple**, all sharing one stem, living in a phase subfolder:

| File | Role | Hard rule |
|---|---|---|
| `{name}_corpus.md` | **Ground truth.** Every real example with source (Cambridge/Oxford URL, COCA sentence + ref, YouGlish clip), IPA, frequency rank. | Every line cited. No invented sentences. |
| `{NAME}.md` | **Readable guide (reference).** What + why + **L1 pitfalls table (Vietnamese→English)** + cheat sheet of ≤8 survival chunks. | Quotes corpus verbatim under `> From {name}_corpus.md:` callouts. |
| `{name}.html` | **Primary learner artifact (what the reader opens first).** Interactive practice player. | Every chunk/dialog line traces to the corpus. |

**Reader flow:** `english/index.html` (dashboard, front door) → card →
`{name}.html` (practice session). The `.md` + `_corpus.md` are **references**
for the curious / auditors.

## 5. The `{name}.html` practice player — required features

Zero-dependency except the **Tailwind v4 browser CDN**. Self-contained (one
file, no build). Must include:
1. **Survival-chunk deck** — ≤8 flip cards (English ↔ meaning + IPA + real
   example), self-rate "knew it / didn't" → spaced practice + `localStorage`.
2. **Real audio per chunk** — ▶ opens a YouGlish/YouTube clip at the moment
   (native audio; **no audio files bundled**).
3. **Dialog role-play** — pick Person A or B (other side hides so *you* play it),
   step-through line-by-line, click a line → see its chunks + hear it.
4. **Shadowing lane** — tap-to-record (`MediaRecorder`, local only, no upload) +
   playback to self-compare.
5. **Writing task** — textarea prompt + reveal-model-answer toggle + copy.
6. **L1 pitfalls table + cheat sheet** (static, mirrors the `.md`).
7. **Mark-finished** syncs with the dashboard via shared `localStorage` key.

### Mandatory `.html` head + shared palette (use verbatim)

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{Title} — English 80/20</title>
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
<style type="text/tailwindcss">
  @theme {
    --color-bg:#0d1117; --color-panel:#161b22; --color-panel2:#0a0e14;
    --color-ink:#e6edf3; --color-muted:#8b949e; --color-border:#30363d;
    --color-grid:#21262d;
    --color-green:#27ae60; --color-teal:#2dd4bf; --color-blue:#58a6ff;
    --color-purple:#b9a9e8; --color-orange:#e67e22; --color-red:#c0392b;
    --color-amber:#f59e0b;
  }
</style>
</head>
<body class="bg-bg text-ink">
  <!-- ... -->
</body>
</html>
```
→ utilities like `bg-bg`, `text-ink`, `text-muted`, `border-border`,
`text-green`, `bg-panel`, etc. State the **offline caveat** in README: pages need
internet to style (Tailwind Play CDN is dev-only per Tailwind's own docs).

## 6. The L1 pitfalls requirement (non-negotiable in every bundle guide)

Each `{NAME}.md` ends with a **Vietnamese → English pitfalls table** — this is
the "expert payoff" (the analog of python's expert gotchas). Seed examples the
docs may cite:

| Vietnamese trap | English fix |
|---|---|
| Drops final consonants ("wen" for "went") | Drill final C + `-ed`/`-s` |
| No tense marking → "Yesterday I go" | Enforce past morphology |
| Omitted articles → "She is teacher" | a/an/the defaults |
| Pro-drop → "Is good" | Supply subject + copula |
| /θ/→/t/, /ð/→/z/ | Tongue-between-teeth drill |
| No plural marking | Enforce `-s` plurals |
| Question word order | Auxiliary-first inversion |

## 7. The daily ritual (the "20% effort", ~20–25 min) — README must include

- **READ** (5 min) — the bundle guide.
- **SHADOW** (7 min) — drill the key chunks + dialog aloud.
- **PRODUCE** (8 min) — speak (record a variant) **or** write (3–5 sentences).
- **Every 7th day = integration day** — one ~10-min conversation simulation
  combining the week's functions (self-recorded); no new bundle.

## 8. Locked decisions (all docs must be consistent with these)

| Area | Decision |
|---|---|
| Bundle model | Triple: `{name}_corpus.md` · `{NAME}.md` · `{name}.html` (primary) |
| Reader entry | `english/index.html` (Tailwind dashboard) → bundle `.html` |
| `.html` styling | Tailwind v4 Play CDN + shared `@theme` dark palette (§5) |
| Cadence | 6-month paced · 180 days · ~2 days/bundle · 90 bundles |
| L1 pitfalls | Vietnamese → English |
| Accent | Both US/UK, flagged per chunk |
| Layout | Subfolders by phase |
| Root link | One small header pill in root `index.html` → `english/index.html` |

## 9. Canonical curriculum — 90 bundles, 6 phases (SINGLE SOURCE OF TRUTH)

> Folder name = the subfolder under `english/`. `#` = bundle index. Day range =
> 2 days/bundle (6-month paced). **Every doc must use these exact stems, titles,
> and day ranges.**

### Phase 0 — Pronunciation (folder `pronunciation/`, Days 1–20, 10 bundles)
| # | Day | stem | title | one-liner |
|---|---|---|---|---|
| 01 | 1–2 | `final_consonants` | Final Consonants & Endings | Fix the #1 Vietnamese intelligibility issue: dropped finals + `-s`/`-ed`. |
| 02 | 3–4 | `th_sounds` | The "th" Sounds /θ/ /ð/ | Tongue-between-teeth; stop substituting /t/ /d/ /z/. |
| 03 | 5–6 | `consonant_clusters` | Consonant Clusters | No inserted vowel ("gro-serry"); keep clusters tight. |
| 04 | 7–8 | `vowel_length` | Long vs Short Vowels | sheep/ship, pull/pool — length changes meaning. |
| 05 | 9–10 | `word_stress` | Word Stress | 2-syllable rules; noun vs verb (REcord/reCORD). |
| 06 | 11–12 | `sentence_stress` | Sentence Stress & Weak Forms | The rhythm: content words strong, grammar words weak. |
| 07 | 13–14 | `linking` | Linking & Connected Speech | Consonant–vowel and consonant–consonant linking. |
| 08 | 15–16 | `reductions` | Reductions | gonna, wanna, "Whaddya", "d'ya". |
| 09 | 17–18 | `intonation` | Intonation | Rising/falling; focus stress changes meaning. |
| 10 | 19–20 | `thought_groups` | Thought Groups & Pausing | Chunk speech into meaning units; breathe between. |

### Phase 1 — Core Speech Acts (folder `speech_acts/`, Days 21–60, 20 bundles)
| # | Day | stem | title | one-liner |
|---|---|---|---|---|
| 11 | 21–22 | `greetings_intros` | Greetings & Introductions | Casual + formal openings; "How's it going?" vs "Pleased to meet you." |
| 12 | 23–24 | `small_talk` | Small Talk | Weather, weekend, plans — the social lubricant. |
| 13 | 25–26 | `thanking` | Thanking & Responding | "That's so kind" / "No worries" / "Anytime." |
| 14 | 27–28 | `apologizing` | Apologizing & Responding | "My bad" → "I apologize for"; graceful acceptance. |
| 15 | 29–30 | `requesting_offering` | Requesting & Offering | Polite requests ("Could you…?") and offers ("Shall I…?"). |
| 16 | 31–32 | `agreeing_disagreeing` | Agreeing & Disagreeing (casual) | "Exactly!" / "Not sure I agree, actually." |
| 17 | 33–34 | `interrupting` | Interrupting & Holding the Floor | "Sorry to interrupt…" / "If I could just finish." |
| 18 | 35–36 | `checking_understanding` | Checking & Confirming | "Does that make sense?" / "So you're saying…" |
| 19 | 37–38 | `clarifying` | Asking for Clarification | "Sorry, I didn't catch that." / "What do you mean by…?" |
| 20 | 39–40 | `opinions_hedged` | Giving Hedged Opinions | "I'd say…" / "Correct me if I'm wrong, but…" |
| 21 | 41–42 | `topic_transitions` | Transitioning Topics | "Speaking of…" / "That reminds me…" / "Anyway." |
| 22 | 43–44 | `closings` | Closing Conversations | "I should let you go." / "Let's catch up soon." |
| 23 | 45–46 | `advising` | Giving Advice & Suggestions | "You might want to…" / "Have you tried…?" |
| 24 | 47–48 | `sympathy` | Sympathy & Concern | "I'm so sorry to hear that." / "That sounds rough." |
| 25 | 49–50 | `anecdotes` | Telling Anecdotes (past narrative) | Past tenses + "So then…" / "The funny thing is…" |
| 26 | 51–52 | `describing_processes` | Describing Processes / How-to | "First you…, then…, make sure to…" |
| 27 | 53–54 | `scheduling` | Making Plans & Scheduling | "Does Tuesday work?" / "Can we push it to 3?" |
| 28 | 55–56 | `preferences` | Expressing Preference | "I'd rather…" / "I prefer X to Y." |
| 29 | 57–58 | `complaining_politely` | Complaining Politely | "I'm afraid there's an issue with…" |
| 30 | 59–60 | `phone_video` | Phone & Video Call Openings/Closings | "Hi, it's X." / "I think we lost them." |

### Phase 2 — Workplace Speaking (folder `workplace/`, Days 61–90, 15 bundles)
| # | Day | stem | title | one-liner |
|---|---|---|---|---|
| 31 | 61–62 | `meeting_openings` | Meeting Openings | "Thanks everyone for joining." / "Let's get started." |
| 32 | 63–64 | `contributing` | Contributing in Meetings | "I'd like to add…" / "Building on what X said." |
| 33 | 65–66 | `diplomatic_disagreement` | Diplomatic Disagreement | "I see your point, however…" / "I wonder if we could…" |
| 34 | 67–68 | `status_updates` | Status Updates & Standups | "Quick update on my side…" / "Blocked on…" |
| 35 | 69–70 | `short_presentations` | Short Presentations | Signposting: "First…, next…, finally…" |
| 36 | 71–72 | `feedback_giving` | Giving Feedback | SBI: "When you…, the impact was…; could you…" |
| 37 | 73–74 | `feedback_receiving` | Receiving Feedback | "Thanks for the feedback; I'll work on that." |
| 38 | 75–76 | `negotiating` | Negotiating | "If you can do X, we could agree to Y." |
| 39 | 77–78 | `interviews_behavioral` | Behavioral Interview Q&A | STAR: Situation, Task, Action, Result. |
| 40 | 79–80 | `networking` | Networking Small Talk | "What brings you here?" / "What do you do?" |
| 41 | 81–82 | `cross_cultural_clarifying` | Cross-Cultural Clarification | Checking meaning politely across accents/cultures. |
| 42 | 83–84 | `video_call_specifics` | Video-Call Specifics | "You're on mute." / "You're frozen." / "Can everyone see?" |
| 43 | 85–86 | `explaining_simply` | Explaining Technical Concepts Simply | "Think of it like…" / analogy-first explanations. |
| 44 | 87–88 | `handling_questions` | Handling Q&A | "That's a great question." / "Let me come back to that." |
| 45 | 89–90 | `delegating_instructions` | Delegating & Giving Instructions | "Could you own X by Y?" — clear, kind, accountable. |

### Phase 3 — Writing (folder `writing/`, Days 91–130, 20 bundles)
| # | Day | stem | title | one-liner |
|---|---|---|---|---|
| 46 | 91–92 | `email_anatomy` | Email Anatomy | Subject line + open + close; the "BLUF" principle. |
| 47 | 93–94 | `formal_casual_register` | Formal vs Casual Register | "I hope this finds you well" vs "Hey, quick one." |
| 48 | 95–96 | `requests_reminders` | Requests & Reminders | "Just a gentle nudge on…" / "Could you… by Friday?" |
| 49 | 97–98 | `apology_emails` | Apology Emails | "I apologize for the delay; here's what happened." |
| 50 | 99–100 | `bad_news_messages` | Bad-News / Sensitive Messages | Buffer → reason → bad news → constructive close. |
| 51 | 101–102 | `meeting_followups` | Meeting Notes & Follow-ups | "As discussed, actions: A (owner) by (date)." |
| 52 | 103–104 | `status_reports` | Status Reports | RAG status, progress, risks, next steps. |
| 53 | 105–106 | `im_slack_style` | IM / Slack Style | Short, scannable, thread-aware, emoji-as-tone. |
| 54 | 107–108 | `linkedin_posts` | LinkedIn / Professional Posts | Hook → value → CTA; professional voice. |
| 55 | 109–110 | `cover_letters` | Cover Letters | "I'm excited to apply because…" + evidence. |
| 56 | 111–112 | `cv_bullets` | CV / Résumé Bullets | Action verbs + metrics: "Led X, resulting in Y%." |
| 57 | 113–114 | `client_messages` | Customer / Client Messages | Empathy first, then solution; professional warmth. |
| 58 | 115–116 | `invitations_thankyous` | Invitations & Thank-You Notes | Warm, specific, timely. |
| 59 | 117–118 | `proposals` | Persuasive Writing / Proposals | Problem → solution → benefits → ask. |
| 60 | 119–120 | `editing_concision` | Editing: Concision & Active Voice | Cut filler; subject-verb-object power. |
| 61 | 121–122 | `editing_hedging` | Editing: Hedging & Tone | Soften without weakening; confidence calibration. |
| 62 | 123–124 | `requests_to_boss` | Upward Requests (to manager) | Frame as benefit + options + clear ask. |
| 63 | 125–126 | `out_of_office_auto` | Out-of-Office & Auto-Replies | Clear dates, coverage, alternative contact. |
| 64 | 127–128 | `complaints_written` | Written Complaints / Disputes | Firm, factual, solution-oriented; no emotion-leak. |
| 65 | 129–130 | `summaries` | Summaries & Executive Briefs | Bottom line up front; 3 bullets max. |

### Phase 4 — Discourse & Nuance (folder `discourse/`, Days 131–160, 15 bundles)
| # | Day | stem | title | one-liner |
|---|---|---|---|---|
| 66 | 131–132 | `hedging_vagueness` | Hedging & Vagueness | "kind of", "a bit", "ish", "around" — softening. |
| 67 | 133–134 | `humor_sarcasm` | Light Humor & Sarcasm | Deadpan delivery; knowing when not to. |
| 68 | 135–136 | `politeness_strategies` | Politeness Strategies | Negative/positive face; indirectness as respect. |
| 69 | 137–138 | `frequency_idioms` | Top-Frequency Idioms | Only the idioms in the top ~200 (no obscure ones). |
| 70 | 139–140 | `phrasal_verbs_work` | Phrasal Verbs: Work | "follow up", "roll out", "push back", "reach out". |
| 71 | 141–142 | `phrasal_verbs_social` | Phrasal Verbs: Social | "hang out", "catch up", "drop by", "chip in". |
| 72 | 143–144 | `collocations` | Collocations | make/do, strong/heavy, take/bring — what sounds right. |
| 73 | 145–146 | `register_switching` | Register Switching | Same idea, three formality levels. |
| 74 | 147–148 | `storytelling_structure` | Storytelling Structures | Setting → tension → turn → payoff. |
| 75 | 149–150 | `discourse_markers` | Discourse Markers | "well", "so", "I mean", "you know", "right". |
| 76 | 151–152 | `fluency_fillers` | Fluency Fillers / Buying Time | "Let me think", "How should I put it". |
| 77 | 153–154 | `vague_language` | Vague Language | "stuff", "things", "and so on" — natural vagueness. |
| 78 | 155–156 | `emphasis_cleft` | Emphasis & Cleft Sentences | "It was X that…", "What I mean is…". |
| 79 | 157–158 | `conditionals_spoken` | Conditionals in Spoken English | Real/unreal; "If I were you…", "I'd have…". |
| 80 | 159–160 | `narrative_tenses` | Narrative Tenses | Past simple + past continuous + past perfect. |

### Phase 5 — Capstone (folder `capstone/`, Days 161–180, 10 bundles)
| # | Day | stem | title | one-liner |
|---|---|---|---|---|
| 81 | 161–162 | `impromptu_talks` | 60-Second Impromptu Talks | Structure a coherent answer in seconds. |
| 82 | 163–164 | `debating` | Debating a Viewpoint | Claim → evidence → rebuttal, calmly. |
| 83 | 165–166 | `live_feedback` | Giving Live Feedback | Real-time, specific, actionable, kind. |
| 84 | 167–168 | `handling_misunderstood` | Handling Being Misunderstood | "Let me put it another way." |
| 85 | 169–170 | `speaking_under_pressure` | Speaking Under Pressure | Composure under tough questions / interviews. |
| 86 | 171–172 | `timed_writing` | Writing Under Time | Outline fast; draft; polish last 10%. |
| 87 | 173–174 | `self_correction` | Self-Correction Strategies | "Sorry, what I meant was…" — fix without freezing. |
| 88 | 175–176 | `sustained_monologue` | Sustained 5-Min Monologue | Coherence, signposting, stamina. |
| 89 | 177–178 | `conversation_simulations` | Full Conversation Simulations | Multi-function, multi-turn, unscripted. |
| 90 | 179–180 | `integration_review` | Integration & Review | Re-drill weak spots; celebrate; plan maintenance. |

**Totals:** 10 + 20 + 15 + 20 + 15 + 10 = **90 bundles**; 90 × 2 days = **180 days**.

## 10. Authoritative sources (workers cite these; docs reference them)

- **Dictionaries:** Cambridge, Oxford Learner's, Collins, Merriam-Webster, Macmillan.
- **Corpora:** COCA / BNC (english-corpora.org), wordfrequency.info (spoken sub-corpus).
- **Audio:** YouGlish (real native clips), Forvo.
- **Writing:** Manchester Academic Phrasebank, business-email corpora.
- **Accent:** flag US/UK per chunk; default dictionaries per variety.

## 11. Verification bar for every bundle (HOW_TO_RESEARCH must encode this)

- Every example in `.md`/`.html` is cited in `_corpus.md` with a source URL.
- IPA pulled from a real dictionary.
- Each guide has the **L1 pitfalls table** + a ≤8-chunk **cheat sheet**.
- `.html` opens, Tailwind styles load, all 7 player features present, audio links valid.
- `## Sources` section at the bottom of every `.md`.

## 12. What each of the three deliverables must contain

### `english/README.md` — mindset + roadmap (learner-facing front matter)
- Title + tagline; **"Start here"**: open `english/index.html`; `.html` is what you
  practice with, `.md`/`_corpus.md` are references.
- The six mindset principles (§3) and the honest "80% native" definition (§2).
- The bundle/artifact model with `.html`-primary framing (§4) + a reader-flow diagram.
- Roadmap overview: a 6-phase summary table (phase · folder · day range · bundle count · theme).
- The daily ritual (§7) incl. Sunday integration.
- "How to use this repo" step list.
- Folder layout tree.
- Pointers to `HOW_TO_RESEARCH.md` (builders) and `CURRICULUM.md` (full day map).
- Honest notes: bundles ship incrementally (dashboard links go live as each
  ships); Tailwind Play CDN needs internet (offline caveat).

### `english/HOW_TO_RESEARCH.md` — the worker law (builder-facing)
**Mirror the structure of `python/HOW_TO_RESEARCH.md`** (study it first), adapted:
- §0 The one rule (every example cited).
- §1 Directory layout (phase subfolders; triple per bundle).
- §2 Three roles of each file (`.html` primary; `.md` + `_corpus.md` references).
- §3 Expert-depth requirement = L1 pitfalls table + real attestation + the 7 player features.
- §4 Orchestrator + workers golden rule (coordinator never hand-writes).
- §5 Worker prompt template (Step 0 absorb + copy style; Step 1 mine sources; Step 2
  web fact-check ≥2 sources; hard rules; deliverables = the triple incl. the
  **Tailwind head + `@theme` from §5 of this spec**; verification; report-back).
  Include the verbatim Tailwind snippet.
- §6 Per-concept brief fields.
- §7 Coordination rules (disjoint ownership, no dep edits, parallel launch, one concept/worker).
- §8 Verification sweep (adapted: every example cited · IPA from dictionary · L1
  pitfalls present · `.html` opens · audio links valid).
- §9 Cross-referencing + a phase-spine mermaid diagram.
- §10 Tooling & sources (§10 of this spec) + the Tailwind offline caveat.
- §11 Failure-modes table (symptom → cause → fix).
- §12 Batch checklist.
- §13 "Why this produces fluency."

### `english/CURRICULUM.md` — the day-by-day map
- Header: 6-month paced, 180 days, ~2 days/bundle, 90 bundles, Sunday integration.
- "How to read this": each bundle = 2 days (Day 1 read+shadow, Day 2 produce+review).
- The 6 phase tables verbatim from §9 of this spec (Day · # · stem · title · one-liner).
- Weekly cadence note (every 7th day = integration).
- Markdown checkboxes `- [ ]` per bundle (TODO style) so it doubles as a progress tracker.
- Daily-ritual reminder box; accent note (US/UK flagged); pointers to README + HOW_TO_RESEARCH.

## 13. Style & formatting rules (all docs)

- Markdown, GitHub-flavored. Use **mermaid** diagrams where they aid understanding
  (reader flow, phase spine, daily ritual) — copy the mermaid idiom from
  `python/HOW_TO_RESEARCH.md`.
- Tables for dense info; callouts (`>`) for key rules.
- Cross-reference sibling docs with relative links: `[CURRICULUM](./CURRICULUM.md)`.
- Tone: direct, expert, encouraging; no filler. Vietnamese learners are the audience
  for README; engineers/builders for HOW_TO_RESEARCH.
- Every doc ends with a "Sources / Further reading" or "Next steps" pointer.

## 14. Out of scope for this pass

Do **not** create: `english/index.html` (dashboard), the root `index.html` pill,
any bundle files, or `SOURCES.md`. Those come after the three docs are approved.
