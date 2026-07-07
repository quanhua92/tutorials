"""
grounding_assertion.py - Reference implementation of post-generation fact-sheet
GROUNDING + ASSERTION for a small language model's answer.

This is the single source of truth that GROUNDING_ASSERTION.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python grounding_assertion.py

== The big idea, in one paragraph (no math) ==================================
A 1B-parameter SLM will cheerfully invent numbers ("revenue was $5.2B", "founded
in 1998", "12000 employees") that SOUND fluent but may be wrong. Trusting the raw
output is unsafe for finance / medical / legal tasks where a wrong number is
unacceptable. GROUNDING fixes this with a POST-GENERATION step: AFTER the model
answers, we (1) PARSE the answer into atomic factual/numerical CLAIMS, (2) look
each claim up in a retrieved FACT SHEET (the RAG context / an internal DB), and
(3) ASSERT: matched claims PASS, claims with no backing fact are FLAGGED, claims
that contradict a known fact are BLOCKED. The answer is only shown to the user
once every claim is accounted for. This is exactly the pipeline RAGAS calls
"faithfulness" and NeMo Guardrails calls the "fact-checking output rail".

== The lineage (old -> new, with WHY) =========================================
  trust-the-model    : emit the model's answer verbatim. Cheap, fast, and
                       WRONG ~ as often as the SLM hallucinates. A 1B model
                       misquotes numbers/facts at a rate no regulated domain
                       can tolerate.
  -> claim EXTRACTION: parse the answer into atomic (entity, attribute, value)
                       triples via regex ("revenue ... $5.2B", "founded ... 1998").
                       You cannot verify what you have not first named.
  -> fact-sheet ASSERT: each triple is looked up in a retrieved ground-truth
                       table { (entity, attribute): value }. With value
                       normalization ("$5.2B" == "5,200,000,000" == "5.2 billion")
                       the lookup is robust to surface form. Outcomes:
                         GROUNDED     - a fact was found and it MATCHES.
                         UNGROUNDED   - no fact found -> cannot confirm -> FLAG.
                         CONTRADICTED - a fact was found and it MISMATCHES -> BLOCK.
  -> verdict POLICY   : strict = any ungrounded/contradicted claim holds the
                       answer (FLAG / BLOCK); lenient = only contradictions hold
                       it (warn on ungrounded). Domain risk picks the policy.

== How this maps to the literature (web-verified, see _reference.txt) ==========
  * RAGAS "faithfulness"  = |claims supported by context| / |total claims|
        (Es et al. 2023, arXiv:2309.15217) -- the metric this pipeline computes.
  * Self-RAG "reflection tokens" = the model itself emits retrieve/critique tokens
        (Asai et al. 2023, arXiv:2310.11511) -- in-model grounding; THIS bundle
        is the post-hoc, model-agnostic counterpart.
  * ALCE citation recall = per-statement NLI(passage => statement); a statement
        is "supported" iff concat(cited passages) entails it (Gao et al. 2023,
        arXiv:2305.14627, Princeton NLP).
  * NeMo Guardrails "self check facts" = an OUTPUT rail that scores the bot
        response against $relevant_chunks (the KB); returns 0.0-1.0; blocking +
        warning modes (NVIDIA docs; Rebedea et al. 2023, arXiv:2310.10501).

== Plain-English glossary ====================================================
    SLM         a small (<5B) language model -- cheap, fast, prone to inventing
                plausible-sounding numbers when its parametric memory is fuzzy.
    claim       an atomic factual/numerical statement pulled OUT of the answer,
                e.g. (entity="Acme", attribute="revenue", value="$5.2B"). One
                sentence often hides several claims.
    fact sheet  a key->value table { (entity, attribute): value } retrieved from
                a TRUSTED source (the RAG context, an internal DB, a 10-K). This
                is the ground truth every claim is checked against.
    grounding   matching a claim to a fact-sheet entry. GROUNDED = match;
                UNGROUNDED = no entry found; CONTRADICTED = entry found, mismatch.
    normalize   mapping surface forms of the SAME number to one value:
                "$5.2B" == "5,200,000,000" == "5.2 billion" -> 5.2e9. Without
                this, a correct claim fails the lookup on formatting alone.
    verdict     the per-answer decision: PASS (all grounded), FLAGGED (>=1
                ungrounded, human review), or BLOCKED (>=1 contradiction).
    policy      strict (any ungrounded claim holds the answer) vs lenient (only
                contradictions hold it; ungrounded gets a warning). Finance /
                medical default to strict; chitchat defaults to lenient.
"""

from __future__ import annotations

import re

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 0. PRETTY PRINTERS + check()  (no raw assert -- compiled out under -O)
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(desc: str, ok: bool):
    """Print '[check] desc: OK' and exit non-zero on failure (never raw assert)."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(1)


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION
#    claim extractor  +  value normalizer  +  fact-sheet verifier  +  policy
# ============================================================================

# canonical attribute -> substring keyword used to spot it in a clause.
# (substring match so "found" catches "founded"/"founding" and "employ" catches
#  "employees"/"employs"/"employment". Iterated in SORTED order for determinism.)
ATTR_KEYWORD: dict[str, str] = {
    "employees": "employ",
    "founded": "found",
    "profit": "profit",
    "revenue": "revenue",
    "users": "user",
}

# numeric/factual span: optional $, digits+commas, optional .frac, optional
# scale suffix (billion/million/thousand or single-letter B/M/K). IGNORECASE so
# "5.2B" and "5.2b" match the same. This is the "numeric claim" detector.
NUM_RE = re.compile(
    r"\$?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand|[bmkbmk])?",
    re.IGNORECASE,
)

# scale suffix -> multiplier. LONG forms first so "billion" beats the bare "b".
SUFFIX_MULT: list[tuple[str, float]] = [
    ("billion", 1e9), ("million", 1e6), ("thousand", 1e3),
    ("b", 1e9), ("m", 1e6), ("k", 1e3),
]


def normalize_value(raw: str) -> float:
    """Map any surface form of a number to one canonical float.

    "$5.2B", "5,200,000,000", "5.2 billion", "5.2b" -> 5.2e9.
    A bare year ("1998") or count ("12000") with no suffix -> itself.
    """
    s = raw.strip().lower().replace("$", "").replace(",", "").replace(" ", "")
    mult = 1.0
    for suf, m in SUFFIX_MULT:
        if s.endswith(suf):
            mult = m
            s = s[: -len(suf)]
            break
    return float(s) * mult


def values_match(a: float, b: float) -> bool:
    """Relative-tolerance equality (torch backend). Treats 5.2e9 from any source
    as equal; rejects 5.3e9 vs 5.2e9 and 1998 vs 1999."""
    return bool(torch.allclose(
        torch.tensor(float(a)), torch.tensor(float(b)), rtol=1e-6, atol=1e-6))


def extract_claims(answer: str, entity: str) -> list[dict]:
    """Parse an answer into atomic (entity, attribute, value) claims.

    Splits on sentence/clause boundaries; each clause yields the FIRST attribute
    keyword it contains plus the FIRST numeric span in that clause. Deterministic:
    clauses stay in text order; attributes are tried in sorted order.
    """
    claims: list[dict] = []
    clauses = re.split(r"[.;]\s+", answer)
    for clause in clauses:
        low = clause.lower()
        for attr in sorted(ATTR_KEYWORD):                 # sorted => deterministic
            kw = ATTR_KEYWORD[attr]
            if kw in low:
                m = NUM_RE.search(clause)
                if m:
                    claims.append({
                        "entity": entity,
                        "attribute": attr,
                        "raw": m.group(0).strip(),
                        "clause": clause.strip(),
                    })
                break                                     # one attribute / clause
    return claims


def verify_claim(claim: dict, fact_sheet: dict) -> str:
    """Return GROUNDED / UNGROUNDED / CONTRADICTED for one claim."""
    key = (claim["entity"], claim["attribute"])
    if key not in fact_sheet:
        return "UNGROUNDED"                               # no fact -> cannot confirm
    fact_val = normalize_value(fact_sheet[key])
    claim_val = normalize_value(claim["raw"])
    return "GROUNDED" if values_match(fact_val, claim_val) else "CONTRADICTED"


def overall_verdict(verdicts: list[str], policy: str) -> tuple[str, int, int, int]:
    """Roll per-claim verdicts into one answer-level decision + counts.

    policy = 'strict'  : any ungrounded -> FLAGGED, any contradiction -> BLOCKED.
    policy = 'lenient' : contradictions -> FLAGGED, ungrounded -> PASS (warned).
    """
    g = sum(1 for v in verdicts if v == "GROUNDED")
    u = sum(1 for v in verdicts if v == "UNGROUNDED")
    c = sum(1 for v in verdicts if v == "CONTRADICTED")
    if policy == "strict":
        if c > 0:
            return "BLOCKED", g, u, c
        if u > 0:
            return "FLAGGED", g, u, c
        return "PASS", g, u, c
    # lenient
    if c > 0:
        return "FLAGGED", g, u, c
    return "PASS", g, u, c


# ============================================================================
# A. CLAIM EXTRACTION -- regex out the numeric/factual claims from a toy answer
# ============================================================================

def section_claim_extraction(answer: str, entity: str):
    banner("SECTION A: claim EXTRACTION -- parse the answer into atomic claims")
    print(f"Entity under review: {entity}")
    print(f"Toy model answer (HARDCODED, deterministic):\n  \"{answer}\"\n")
    claims = extract_claims(answer, entity)
    print(f"Extracted {len(claims)} claim(s):\n")
    print("| # | entity | attribute | value (raw) | source clause")
    print("|---|--------|-----------|-------------|-------------------------------------")
    for i, cl in enumerate(claims):
        print(f"| {i + 1} | {cl['entity']} | {cl['attribute']:<9} | "
              f"{cl['raw']:<11} | {cl['clause']}")
    print()
    print("Key: the extractor pulled ONE (entity, attribute, value) triple out of")
    print("each clause. These are the atoms the fact sheet will be asked about.")
    print("Nothing here is verified yet -- extraction is just 'name the claims'.")
    check("extractor found exactly 3 claims", len(claims) == 3)
    check("claims are (revenue, founded, employees) in text order",
          [c["attribute"] for c in claims] == ["revenue", "founded", "employees"])
    return claims


# ============================================================================
# B. FACT-SHEET LOOKUP -- per-claim verdict (GROUNDED/UNGROUNDED/CONTRADICTED)
# ============================================================================

def section_fact_sheet_lookup(claims: list[dict], fact_sheet: dict):
    banner("SECTION B: fact-sheet LOOKUP -- verify each claim against ground truth")
    print("Fact sheet (the retrieved ground-truth table):\n")
    print("| (entity, attribute) | value (raw) | normalized")
    print("|---------------------|-------------|------------")
    for key in sorted(fact_sheet):                        # sorted => deterministic
        v = fact_sheet[key]
        print(f"| {str(key):<19} | {v:<11} | {normalize_value(v):.4g}")
    print()
    print("NOTE: ('Acme','employees') is ABSENT from the sheet on purpose --\n"
          "      any employee claim is therefore UNGROUNDED (cannot confirm).\n")
    print("Per-claim verdict:\n")
    print("| # | attribute | claim raw | fact raw | claim val | fact val | verdict")
    print("|---|-----------|-----------|----------|-----------|----------|------------")
    verdicts: list[str] = []
    for i, cl in enumerate(claims):
        v = verify_claim(cl, fact_sheet)
        verdicts.append(v)
        key = (cl["entity"], cl["attribute"])
        fact_raw = fact_sheet.get(key, "-")
        fact_val = normalize_value(fact_raw) if key in fact_sheet else float("nan")
        print(f"| {i + 1} | {cl['attribute']:<9} | {cl['raw']:<9} | "
              f"{str(fact_raw):<8} | {normalize_value(cl['raw']):<9.4g} | "
              f"{(fact_val if fact_val == fact_val else 0):<8.4g} | {v}")
    print()
    g = verdicts.count("GROUNDED")
    u = verdicts.count("UNGROUNDED")
    c = verdicts.count("CONTRADICTED")
    print(f"counts: GROUNDED={g}  UNGROUNDED={u}  CONTRADICTED={c}")
    check("revenue claim is GROUNDED", verdicts[0] == "GROUNDED")
    check("founded claim is GROUNDED", verdicts[1] == "GROUNDED")
    check("employees claim is UNGROUNDED (no sheet entry)", verdicts[2] == "UNGROUNDED")
    check("contradiction count is 0 on the gold answer", c == 0)
    return verdicts


# ============================================================================
# C. VALUE NORMALIZATION -- "$5.2B" == "5,200,000,000" == "5.2 billion"
# ============================================================================

def section_normalization():
    banner("SECTION C: value NORMALIZATION -- surface forms of the SAME number")
    forms = ["$5.2B", "5,200,000,000", "5.2 billion", "5.2b", "5200000000"]
    print("All of these are the SAME number; the normalizer maps them to one float:\n")
    print("| raw form          | normalized | matches '$5.2B'?")
    print("|-------------------|------------|------------------")
    ref = normalize_value("$5.2B")
    for f in forms:
        n = normalize_value(f)
        print(f"| {f:<17} | {n:<10.4g} | {values_match(n, ref)}")
    print()
    print("Without normalization a CORRECT '$5.2B' claim would fail to match a")
    print("'5,200,000,000' fact-sheet entry on formatting alone -- a false negative.")
    all_same = all(values_match(normalize_value(f), ref) for f in forms)
    check("all 5 surface forms normalize to the same value", all_same)
    # the contradiction case: a CLOSE but WRONG number must NOT match
    bad = normalize_value("5.3B")
    print(f"\nContradiction check: '5.3B' -> {bad:.4g}  vs  '$5.2B' -> {ref:.4g}")
    print(f"  match? {values_match(bad, ref)}  -> a close-but-wrong number is CONTRADICTED.")
    check("'5.3B' does NOT match '$5.2B' (contradiction survives)",
          not values_match(bad, ref))
    # year edge case: bare 4-digit year must NOT pick up a scale suffix
    print(f"\nEdge case: '1998' -> {normalize_value('1998'):.4g} "
          f"(bare year, no suffix -> stays 1998).")
    check("bare year '1998' normalizes to 1998 (no false suffix)",
          values_match(normalize_value("1998"), 1998.0))


# ============================================================================
# D. END-TO-END -- three toy answers -> FLAGGED / PASS / BLOCKED + policy toggle
# ============================================================================

def section_end_to_end(fact_sheet: dict):
    banner("SECTION D: end-to-end on three toy answers (strict policy)")
    answers = [
        ("FLAGGED (gold)",
         "Acme Corp reported revenue of $5.2B in 2023. The company was founded "
         "in 1998. It employs 12000 people."),
        ("PASS",
         "Acme was founded in 1998. Revenue was $5.2 billion."),
        ("BLOCKED",
         "Acme was founded in 1999."),
    ]
    print("Three answers, same fact sheet, STRICT policy "
          "(any ungrounded -> FLAGGED, any contradiction -> BLOCKED):\n")
    print("| answer | claims | G | U | C | verdict")
    print("|--------|--------|---|---|---|---------")
    for label, ans in answers:
        claims = extract_claims(ans, "Acme")
        verdicts = [verify_claim(c, fact_sheet) for c in claims]
        verdict, g, u, c = overall_verdict(verdicts, "strict")
        print(f"| {label:<15} | {len(claims):<6} | {g} | {u} | {c} | {verdict}")
    print()
    print("Policy TOGGLE on the SAME gold answer (3 claims: 2 grounded, 1 ungrounded):")
    gold = answers[0][1]
    claims = extract_claims(gold, "Acme")
    verdicts = [verify_claim(c, fact_sheet) for c in claims]
    for policy in ("strict", "lenient"):
        verdict, g, u, c = overall_verdict(verdicts, policy)
        print(f"  policy={policy:<7} -> verdict={verdict:<8} (G={g}, U={u}, C={c})")
    print("\n  strict  : the unverified employee count HOLDS the answer -> FLAGGED.")
    print("  lenient : ungrounded is only a warning -> PASS (contradictions still block).")
    vs, g, u, c = overall_verdict(verdicts, "strict")
    check("strict verdict on gold answer is FLAGGED", vs == "FLAGGED")
    vl, _, _, _ = overall_verdict(verdicts, "lenient")
    check("lenient verdict on gold answer is PASS (ungrounded allowed)",
          vl == "PASS")


# ============================================================================
# E. THE GOLD TABLE -- the pinned centerpiece (recomputed identically by .html)
# ============================================================================

def section_gold_table(answer: str, fact_sheet: dict):
    banner("SECTION E: the GOLD TABLE -- pinned for grounding_assertion.html")
    print("The .html recomputes THIS table from the SAME answer + fact sheet in JS\n"
          "and gold-checks the pinned tuple below.\n")
    claims = extract_claims(answer, "Acme")
    verdicts = [verify_claim(c, fact_sheet) for c in claims]
    g = verdicts.count("GROUNDED")
    u = verdicts.count("UNGROUNDED")
    c = verdicts.count("CONTRADICTED")
    verdict, _, _, _ = overall_verdict(verdicts, "strict")
    print("| num_claims | grounded | ungrounded | contradicted | verdict (strict)")
    print("|------------|----------|------------|--------------|------------------")
    print(f"| {len(claims):<10} | {g:<8} | {u:<10} | {c:<12} | {verdict}")
    print()
    print("GOLD PINS (grounding_assertion.html recomputes and diffs these):")
    print(f"    num_claims  = {len(claims)}")
    print(f"    grounded    = {g}")
    print(f"    ungrounded  = {u}")
    print(f"    contradicted= {c}")
    print(f"    verdict     = '{verdict}'")
    gold = (len(claims) == 3 and g == 2 and u == 1 and c == 0 and verdict == "FLAGGED")
    check("GOLD PIN (3,2,1,0,FLAGGED) holds", gold)
    # torch verdict matrix: rows=claims, cols=[GROUNDED, UNGROUNDED, CONTRADICTED] one-hot
    idx = {"GROUNDED": 0, "UNGROUNDED": 1, "CONTRADICTED": 2}
    mat = torch.zeros(len(verdicts), 3)
    for i, v in enumerate(verdicts):
        mat[i, idx[v]] = 1.0
    print(f"\ntorch verdict matrix (one-hot per claim):\n{mat}")
    check("verdict matrix row-sums are all 1 (one verdict per claim)",
          bool(torch.allclose(mat.sum(dim=1), torch.ones(len(verdicts)))))


# ============================================================================
# F. LINEAGE RECAP + CHEAT SHEET
# ============================================================================

def section_lineage_cheatsheet():
    banner("SECTION F: lineage recap + cheat sheet")
    print("The post-generation verification pipeline, old -> new:\n")
    rows = [
        ("trust-the-model", "emit answer verbatim",
         "hallucinated numbers slip straight through to the user"),
        ("claim EXTRACTION", "regex-parse answer -> (entity, attr, value)",
         "you cannot verify what you have not first named"),
        ("fact-sheet ASSERT", "lookup each claim in retrieved ground truth",
         "GROUNDED / UNGROUNDED / CONTRADICTED per claim"),
        ("verdict POLICY", "strict holds on ungrounded; lenient only on contradict",
         "domain risk picks the policy"),
    ]
    print("| stage             | what it does                               | why")
    print("|-------------------|--------------------------------------------|-------------------------")
    for stage, does, why in rows:
        print(f"| {stage:<17} | {does:<42} | {why}")
    print()
    print("Cheat sheet:")
    print("  * extract  : split answer on [.];]  ; first attr-keyword + first NUM_RE")
    print("               span per clause  ->  list[(entity, attr, raw_value)]")
    print("  * normalize: strip $/,/space, lower; suffix B/billion=1e9, M/million=1e6,")
    print("               K/thousand=1e3 ; bare year/count stays itself")
    print("  * verify   : key=(entity,attr);  not in sheet -> UNGROUNDED ;")
    print("               match (rtol 1e-6) -> GROUNDED ; else CONTRADICTED")
    print("  * verdict  : strict  -> any U=FLAGGED, any C=BLOCKED, else PASS")
    print("               lenient -> any C=FLAGGED, else PASS (U is just a warning)")
    print("  * torch    : values_match = torch.allclose(rtol=1e-6, atol=1e-6)")
    print("  * GOLD     : 3-claim toy answer -> (3, 2 grounded, 1 ungrounded, FLAGGED)")


# ============================================================================
# main
# ============================================================================

def main():
    print("grounding_assertion.py - reference impl (post-generation fact-sheet "
          "verification).\nNumbers below feed GROUNDING_ASSERTION.md.  "
          f"torch = {torch.__version__}")

    # ---- the FIXED toy inputs (deterministic; no RNG, no wall-clock) --------
    ENTITY = "Acme"
    GOLD_ANSWER = (
        "Acme Corp reported revenue of $5.2B in 2023. The company was founded "
        "in 1998. It employs 12000 people."
    )
    FACT_SHEET = {
        ("Acme", "revenue"): "5200000000",    # == $5.2B  -> GROUNDED
        ("Acme", "founded"): "1998",          # == 1998   -> GROUNDED
        # ("Acme", "employees") INTENTIONALLY ABSENT -> employee claim UNGROUNDED
    }

    claims = section_claim_extraction(GOLD_ANSWER, ENTITY)
    section_fact_sheet_lookup(claims, FACT_SHEET)
    section_normalization()
    section_end_to_end(FACT_SHEET)
    section_gold_table(GOLD_ANSWER, FACT_SHEET)
    section_lineage_cheatsheet()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
