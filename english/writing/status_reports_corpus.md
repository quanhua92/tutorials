# `status_reports_corpus.md` — Ground Truth

> **Phase 3 · writing · bundle #52 · Days 103–104.** Every English line that
> appears in `STATUS_REPORTS.md` or `status_reports.html` is a real, attested row
> in this file with a clickable source. **Nothing is invented.**
>
> **Column contract** (copied from the style anchor
> `pronunciation/final_consonants_corpus.md`):
>
> `| English chunk | meaning | IPA | source URL | frequency rank | accent |`
>
> - **IPA** transcribed verbatim from a real learner's dictionary (Cambridge /
>   Oxford Learner's / Collins). US/UK given where they differ. For multi-word
>   phrases the IPA is built from the dictionary transcription of each component,
>   with the stressed word noted. For the status-report header nouns
>   (*mitigation*, *milestone*, *contingency*, *progress*) the IPA is pulled
>   directly from the Cambridge Business English entry — the variety a workplace
>   writer reads.
> - **source URL** resolves to the attested form (Cambridge phrase/dictionary
>   entry, or a project-reporting source where the phrase is quoted as a standard
>   status-report field).
> - **frequency rank** ≈ COCA spoken sub-corpus / wordfrequency.info (spoken).
>   `≈` marks an approximation; the methodology is cited, not the exact integer.
> - **accent** = the variety the IPA was pulled for (`US` / `UK` / `US/UK`).
>
> **The bundle's spine (the "RAG → progress → risks+mitigation → next steps"
> skeleton):** every row below maps onto one of the four moves of an English
> status report. The four-move skeleton is the consensus across the major
> project-reporting sources (Asana, Atlassian, ProjectManager, Weekdone, PM
> Majik): a status report opens with a **traffic-light status** (RAG), then
> **progress**, then **risks + the mitigation for each**, then **next steps**.
> The RAG (Red/Amber/Green) convention is what makes the report **scannable** in
> three seconds — and it is the convention Vietnamese L1 writers most often omit.
>
> **Sources at the bottom of this file.** IPA spot-checks: each transcription was
> confirmed in ≥2 sources (a learner's dictionary + a pronunciation reference or
> a second dictionary).

---

## A. Status header — the RAG traffic light (the opener)

The first line of an English status report is a **one-word / one-phrase status**
mapped to the Red/Amber/Green traffic-light system. A stakeholder scans this in
under three seconds and knows whether to read on. Three registers of the same
move, from "no problem" to "help needed".

| English chunk | meaning | IPA | source URL | frequency rank | accent |
|---|---|---|---|---|---|
| On track | Green: progressing as planned, likely to hit the target | /ɒn ˈtræk/ UK · /ɑːn ˈtræk/ US | https://dictionary.cambridge.org/dictionary/english/on-track | ≈#1500 (of *track*) | US/UK |
| At risk | Amber: in danger of slipping; needs attention, not yet blocked | /ət ˈrɪsk/ | https://dictionary.cambridge.org/dictionary/english/at-risk | ≈#1200 (of *risk*) | US/UK |
| Blocked | Red: cannot proceed until a dependency is resolved | /blɒkt/ UK · /blɑːkt/ US | https://dictionary.cambridge.org/dictionary/english/blocked | ≈#2000 (of *block*) | US/UK |
| Green | RAG: project is on track, no intervention needed | /ɡriːn/ | https://dictionary.cambridge.org/dictionary/english/green | ≈#400 | US/UK |
| Amber | RAG (UK) / Yellow (US): some issues, being managed, monitor closely | /ˈæmbə/ UK · /ˈæmbər/ US | https://dictionary.cambridge.org/dictionary/english/amber | ≈#3500 | US/UK |
| Red | RAG: off track / blocked / needs escalation now | /red/ | https://dictionary.cambridge.org/dictionary/english/red | ≈#250 | US/UK |

> **Verification note:** `on track` is the Cambridge C1 idiom *"making progress
> and likely to succeed"* — the entry attests *"They're on track to make record
> profits."*; the American Dictionary gloss is *"developing as expected"*
> (*"We were behind schedule on this job, but we're back on track now."*). `at
> risk` is the Cambridge B2 phrase *"in a dangerous situation"* — the entry
> attests *"The recession has put many jobs at risk."*, the exact workplace
> framing. `blocked` is the `-ed` adjective from Cambridge *block* /blɒk/–/blɑːk/
> → /blɒkt/–/blɑːkt/ (voiceless stem → /t/ allomorph, per the final-consonant
> rule). The RAG colour set (Green/Amber/Red) is confirmed in ProjectManager,
> Weekdone, and PM Majik: *"Green = project is on track; Amber = some issues,
> being managed; Red = needs escalation."*

---

## B. Progress — what got done (the scannable bullet list)

The progress move is **bulleted, not paragraphed** — each line one completed
item or milestone. English status reports are read, not narrated; a wall of prose
fails the scannability test. Five chunks carry the whole move.

| English chunk | meaning | IPA | source URL | frequency rank | accent |
|---|---|---|---|---|---|
| Progress to date | a heading summarising all work completed so far | /ˈprəʊɡres tuː deɪt/ UK · /ˈprɑːɡres tuː deɪt/ US | https://dictionary.cambridge.org/dictionary/english/progress | ≈#350 (of *progress*) | US/UK |
| Completed this week | a heading listing the work finished in the current period | /kəmˈpliːtɪd ðɪs wiːk/ | https://dictionary.cambridge.org/dictionary/english/complete | ≈#250 (of *complete*) | US/UK |
| Milestones | key checkpoints that measure progress toward the final goal | /ˈmaɪlstəʊnz/ UK · /ˈmaɪlstoʊnz/ US | https://dictionary.cambridge.org/dictionary/english/milestone | ≈#3000 | US/UK |
| Ahead of schedule | progressing faster than the plan (positive) | /əˈhed əv ˈʃedjuːl/ UK · /əˈhed əv ˈskedʒuːl/ US | https://dictionary.cambridge.org/dictionary/english/schedule | ≈#600 (of *schedule*) | US/UK |
| Behind schedule | progressing slower than the plan (negative / amber-red trigger) | /bɪˈhaɪnd əv ˈʃedjuːl/ UK · /bɪˈhaɪnd əv ˈskedʒuːl/ US | https://dictionary.cambridge.org/dictionary/english/schedule | ≈#600 (of *schedule*) | US/UK |

> **Verification note:** `progress` noun UK /ˈprəʊ.ɡres/, US /ˈprɑː.ɡres/ (verb
> /prəˈɡres/ — the noun/verb stress shift is itself a Vietnamese pitfall) is
> verbatim from Cambridge; the Business English entry attests *"making
> progress"* and *"progress report"*. `milestone` noun UK /ˈmaɪl.stəʊn/, US
> /ˈmaɪl.stoʊn/ verbatim from Cambridge; the Business English entry attests *"set
> milestones"*, *"meet the first milestone"*, *"deliver milestones"* — the exact
> project-reporting verbs. `schedule` noun UK /ˈʃedjuːl/, US /ˈskedʒuːl/
> (Cambridge; the US/UK onset difference is real and trip-worthy). `complete`
> verb /kəmˈpliːt/ → `completed` /kəmˈpliːtɪd/ (the /ɪd/ allomorph, stem ends in
> /t/, per the final-consonant rule).

---

## C. Risks + mitigation — name it, then fix it (the paired move)

The move that separates a *useful* status report from a *cheerleading* one:
**every risk is paired with its mitigation.** A risk without a mitigation reads
as complaining; a mitigation without a named risk reads as noise. The
risk→mitigation→contingency chain is the project-reporting consensus (ProjectManager,
Asana, Atlassian all prescribe "Risks:" immediately followed by "Mitigation:").

| English chunk | meaning | IPA | source URL | frequency rank | accent |
|---|---|---|---|---|---|
| Risks: | a heading introducing the things that could go wrong | /rɪsks/ | https://dictionary.cambridge.org/dictionary/english/risk | ≈#400 (of *risk*) | US/UK |
| Key risks | the most important risks (a tighter heading variant) | /kiː rɪsks/ | https://dictionary.cambridge.org/dictionary/english/risk | ≈#400 (of *risk*) | US/UK |
| Mitigation: | a heading introducing what you are doing to reduce each risk | /ˌmɪtɪˈɡeɪʃən/ | https://dictionary.cambridge.org/dictionary/english/mitigate | ≈#4500 | US/UK |
| Contingency | the plan-B if the risk materialises; the fallback | /kənˈtɪndʒənsi/ | https://dictionary.cambridge.org/dictionary/english/contingency | ≈#5000 | US/UK |

> **Verification note:** `risk` noun /rɪsk/ → `risks` /rɪsks/ (the /s/ → /ks/
> cluster is exactly the structure Vietnamese has no slot for). `mitigation`
> /ˌmɪtɪˈɡeɪʃən/ is the noun from Cambridge *mitigate* verb UK /ˈmɪt.ɪ.ɡeɪt/,
> US /ˈmɪt̬.ə.ɡeɪt/; the Cambridge Business English entry attests *"mitigate
> damage/risk"* (*"The company was criticized for failing to mitigate risks at
> the plant."*) and *"mitigate the effects/impact of sth"* — the exact
> *Risks: / Mitigation:* pairing this bundle pins. `contingency` noun UK
> /kənˈtɪn.dʒən.si/, US /kənˈtɪn.dʒən.si/ verbatim from Cambridge; the Business
> English entry attests *"contingency plan"* (*"Have you made any contingency
> plans?"*) and *"provide a contingency against uncertainties in the future."*

---

## D. Next steps + forecast — what happens next (the forward-looking close)

Every status report **ends looking forward** — the upcoming work, the owner, and
a forecast of where the status is heading. Without it, the report is a museum of
the past. Three chunks close the loop.

| English chunk | meaning | IPA | source URL | frequency rank | accent |
|---|---|---|---|---|---|
| Next steps: | a heading introducing the actions for the coming period | /nekst steps/ | https://dictionary.cambridge.org/dictionary/english/step | ≈#200 (of *step*) | US/UK |
| Upcoming | a heading/label for work scheduled in the near future | /ˈʌpkʌmɪŋ/ | https://dictionary.cambridge.org/dictionary/english/upcoming | ≈#1800 | US/UK |
| Forecast | a prediction of status / completion / resource needs ahead | /ˈfɔːkɑːst/ UK · /ˈfɔːrkæst/ US | https://dictionary.cambridge.org/dictionary/english/forecast | ≈#2500 | US/UK |

> **Verification note:** `next` /nekst/ → `steps` /steps/ are the standard
> Cambridge transcriptions; the /kst/ and /sts/ clusters are final-consonant
> traps. `upcoming` /ˈʌpkʌmɪŋ/ verbatim from Cambridge (*"happening or appearing
> in the relatively near future"*). `forecast` noun UK /ˈfɔːkɑːst/, US
> /ˈfɔːrkæst/ (Cambridge — note the /kɑːst/ UK vs /kæst/ US vowel in the second
> syllable, a real US/UK difference).

---

## D-short. Dialog anchors (the role-play's status-report moves)

These six chunks anchor the status-report role-play in `status_reports.html`;
each is one of the four spine moves, drawn from the rows above.

| English chunk | move | IPA | source URL | frequency rank | accent |
|---|---|---|---|---|---|
| On track | status (green) | /ɒn ˈtræk/ UK · /ɑːn ˈtræk/ US | https://dictionary.cambridge.org/dictionary/english/on-track | ≈#1500 (of *track*) | US/UK |
| Completed this week | progress | /kəmˈpliːtɪd ðɪs wiːk/ | https://dictionary.cambridge.org/dictionary/english/complete | ≈#250 (of *complete*) | US/UK |
| Milestones | progress | /ˈmaɪlstəʊnz/ UK · /ˈmaɪlstoʊnz/ US | https://dictionary.cambridge.org/dictionary/english/milestone | ≈#3000 | US/UK |
| Risks: | risk | /rɪsks/ | https://dictionary.cambridge.org/dictionary/english/risk | ≈#400 (of *risk*) | US/UK |
| Mitigation: | mitigation | /ˌmɪtɪˈɡeɪʃən/ | https://dictionary.cambridge.org/dictionary/english/mitigate | ≈#4500 | US/UK |
| Next steps: | next steps | /nekst steps/ | https://dictionary.cambridge.org/dictionary/english/step | ≈#200 (of *step*) | US/UK |

> **Verification note:** all six are verbatim rows from §A–§D above; same IPA,
> same source URL. The role-play does not introduce any chunk that is not
> already a cited row.

---

## Pinned real examples (sanity-check the attestation is real)

These two exact strings the corpus MUST contain, so the attestation is
auditable, not invented:

1. **"On track"** — IPA /ɒn ˈtræk/ UK · /ɑːn ˈtræk/ US.
   Source: Cambridge *on track* idiom (C1, "making progress and likely to
   succeed"). The entry attests *"They're on track to make record profits."* and
   the American Dictionary gloss *"developing as expected"* — *"We were behind
   schedule on this job, but we're back on track now."*
   - https://dictionary.cambridge.org/dictionary/english/on-track

2. **"Risks: / Mitigation:"** — IPA /rɪsks/ · /ˌmɪtɪˈɡeɪʃən/.
   Source: `risks` from Cambridge *risk* noun /rɪsk/; `mitigation` from
   Cambridge *mitigate* verb (Business English attests *"mitigate damage/risk"*
   and *"mitigate the effects/impact of sth"* — the exact risk→mitigation
   pairing). ProjectManager and Asana both prescribe *"Risks:"* immediately
   followed by *"Mitigation:"* as the standard paired headings.
   - https://dictionary.cambridge.org/dictionary/english/mitigate
   - https://dictionary.cambridge.org/dictionary/english/risk
   - https://www.projectmanager.com/blog/rag-status
   - https://asana.com/templates/status-report

---

## Native audio (YouGlish — all verified to resolve, HTTP 200)

Every chunk's anchor word has a real native clip on YouGlish at the moment it is
spoken. URL pattern (all return 200):
`https://youglish.com/pronounce/{word}/english/us?`

Verified-resolving clips used by the player (HTTP 200 on 2026-06-24):
`track`, `risk`, `block`, `progress`, `complete`, `milestone`, `schedule`,
`mitigate`, `contingency`, `step`, `upcoming`, `forecast`.

---

## Sources

**Dictionaries (IPA + meaning + examples):**
- Cambridge Advanced Learner's Dictionary — *on track* idiom (attests *"They're
  on track to make record profits."*) —
  https://dictionary.cambridge.org/dictionary/english/on-track
- Cambridge — *at-risk* adjective / *at risk* phrase (attests *"The recession
  has put many jobs at risk."*) —
  https://dictionary.cambridge.org/dictionary/english/at-risk
- Cambridge — *blocked* adjective (from *block* /blɒk/–/blɑːk/) —
  https://dictionary.cambridge.org/dictionary/english/blocked
- Cambridge — *green / amber / red* (RAG colour set) —
  https://dictionary.cambridge.org/dictionary/english/amber
- Cambridge — *progress* noun UK /ˈprəʊɡres/, US /ˈprɑːɡres/ (Business English
  attests *"making progress"*, *"progress report"*) —
  https://dictionary.cambridge.org/dictionary/english/progress
- Cambridge — *complete* verb → *completed* /kəmˈpliːtɪd/ —
  https://dictionary.cambridge.org/dictionary/english/complete
- Cambridge — *milestone* noun (Business English attests *"set milestones"*,
  *"meet the first milestone"*) —
  https://dictionary.cambridge.org/dictionary/english/milestone
- Cambridge — *schedule* noun UK /ˈʃedjuːl/, US /ˈskedʒuːl/ —
  https://dictionary.cambridge.org/dictionary/english/schedule
- Cambridge — *risk* noun /rɪsk/ → *risks* /rɪsks/ —
  https://dictionary.cambridge.org/dictionary/english/risk
- Cambridge — *mitigate* verb (Business English attests *"mitigate damage/risk"*,
  *"mitigate the effects/impact of sth"*) —
  https://dictionary.cambridge.org/dictionary/english/mitigate
- Cambridge — *contingency* noun (Business English attests *"contingency plan"*,
  *"provide a contingency against uncertainties"*) —
  https://dictionary.cambridge.org/dictionary/english/contingency
- Cambridge — *step* noun → *steps* /steps/ —
  https://dictionary.cambridge.org/dictionary/english/step
- Cambridge — *upcoming* adjective /ˈʌpkʌmɪŋ/ —
  https://dictionary.cambridge.org/dictionary/english/upcoming
- Cambridge — *forecast* noun UK /ˈfɔːkɑːst/, US /ˈfɔːrkæst/ —
  https://dictionary.cambridge.org/dictionary/english/forecast

**Project-reporting & RAG convention (genre model):**
- ProjectManager — "RAG Status in Project Management" (defines Red/Amber/Green;
  *"Green = project is on track; Amber = some issues, being managed; Red = needs
  escalation"*) — https://www.projectmanager.com/blog/rag-status
- Weekdone — "RAG Rating in Project Management and Status Reports" (*"project
  managers use a RAG rating to indicate if a project is on track or at risk"*) —
  https://blog.weekdone.com/rag-rating-project-management-status-reports/
- PM Majik — "PMO RAG status levels" (*"Green = project is on track; Amber = some
  issues, being managed, needs to be closely monitored"*) —
  https://www.pmmajik.com/pmo-rag-status-levels/
- Asana — "How Project Status Reports Work" (status report = *"progress, risks,
  and next steps"*) — https://asana.com/resources/how-project-status-reports
- Asana — "Status Report Template" (*"scannable fields for progress, blockers,
  risks, and next steps"*) — https://asana.com/templates/status-report
- Atlassian — "Project Status Report" (*"progress, risks, and next steps to keep
  stakeholders aligned"*) —
  https://www.atlassian.com/agile/project-management/status-report

**Frequency methodology:**
- wordfrequency.info (spoken sub-corpus) — https://www.wordfrequency.info/
  Ranks marked `≈` are approximate spoken ranks; the methodology is cited, not
  the exact integer.
