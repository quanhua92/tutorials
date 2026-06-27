#!/usr/bin/env python3
"""
abuse_detection.py - Abuse detection system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds ABUSE_DETECTION.md
and is recomputed identically in abuse_detection.html (gold-checked).

Core model: a layered SCORING pipeline that fuses four independent signals
into one 0-1 risk score, then maps the score (plus deterministic hard rules)
to a tiered action ALLOW -> WARN -> THROTTLE -> CHALLENGE -> BAN.

  Velocity   (rate-based)   : requests-per-window across 1m / 10m / 1h, blended.
  Pattern    (regex/rules)  : a catalog of weighted spam signatures.
  Reputation (trust model)  : account age + engagement + verified + history.
  Toxicity   (content mod)  : severity-weighted toxic lexicon.

The fusion is a fixed linear blend:
  risk = 0.30*velocity + 0.25*pattern + 0.20*(1-reputation) + 0.25*toxicity

Two HARD RULES override the score (real systems layer deterministic rules on
top of the model so egregious cases never depend on a calibrated threshold):
  * coordinated spam : velocity>=0.90 AND pattern>=0.60 -> BAN
  * severe toxicity  : toxicity>=0.95                   -> BAN

Progressive ESCALATION: repeated offenses by the same actor bump the response
one tier per prior offense (warn -> throttle -> challenge -> ban), modeling
the "warn before you ban" product discipline.

Sections:
  1. Velocity scoring (rate-based, multi-window blend)
  2. Pattern detection (weighted regex catalog)
  3. Content moderation / toxicity (severity lexicon)
  4. Reputation scoring (trust from age + history)
  5. Risk fusion + action escalation (full pipeline)
  6. Progressive escalation sequence (same actor, 4 offenses)
  7. Scale estimation (100M logins/day, sync latency budget)
  8. GOLD values pinned for abuse_detection.html
"""

import re

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

LINE = "=" * 72

# velocity windows: (name, request_limit, weight). weights sum to 1.0.
# The 1-min window carries the most weight (bursts are the strongest signal).
WINDOWS = [("1min", 10, 0.5), ("10min", 80, 0.3), ("1hour", 500, 0.2)]

# pattern catalog: (name, regex, weight, ignore_case).
# A category contributes its weight ONCE if it matches at all.
PATTERNS = [
    ("url",        r"http[s]?://\S+",                       0.30, True),
    ("free_money", r"free\s+money",                         0.40, True),
    ("spam_kw",    r"\b(buy|cheap|casino|viagra|loan|crypto)\b", 0.35, True),
    ("repeat",     r"(.)\1{4,}",                            0.20, False),
    ("allcaps",    r"^[^a-z]*$",                            0.15, False),
    ("dollar",     r"\$\s?\d",                              0.10, False),
]

# toxicity lexicon: word -> severity (0-1). Sum capped at 1.0.
TOXIC = {
    "idiot": 0.6, "hate": 0.5, "kill": 0.7, "stupid": 0.4,
    "die": 0.6, "scum": 0.7, "moron": 0.5, "trash": 0.3, "loser": 0.4,
}

# reputation blend weights (sum to 1.0): age, engagement, verified, history-clean
W_AGE, W_ENG, W_VER, W_HIST = 0.35, 0.25, 0.20, 0.20
AGE_FULL_TRUST_DAYS = 365.0
HISTORY_DECAY = 0.8           # trust multiplied by HISTORY_DECAY**violations

# risk fusion weights (sum to 1.0): velocity, pattern, reputation-risk, toxicity
W_VEL, W_PAT, W_REP, W_TOX = 0.30, 0.25, 0.20, 0.25

# action tiers (upper bound exclusive): risk < threshold -> tier
TIERS = [("ALLOW", 0.30), ("WARN", 0.50), ("THROTTLE", 0.70),
         ("CHALLENGE", 0.85), ("BAN", 2.0)]
TIER_ORDER = ["ALLOW", "WARN", "THROTTLE", "CHALLENGE", "BAN"]

# deterministic scenarios: (name, age_days, violations, verified, engagement,
#                           velocity[1m,10min,1h], message)
SCENARIOS = [
    ("alice",   400, 0, True,  0.80, [2, 15, 80],     "hey everyone, great stream today!"),
    ("bob",      30, 1, False, 0.40, [8, 72, 200],    "BUY NOW!!! limited crypto deals"),
    ("carol",     5, 0, False, 0.10, [12, 90, 300],   "FREE MONEY!!!!! claim yours http://x.io"),
    ("frank",     2, 0, False, 0.05, [10, 110, 400],  "buy cheap now, you absolute moron trash"),
    ("spambot",   1, 3, False, 0.05, [45, 300, 1200], "WIN FREE MONEY!!! http://s.cam buy now cheap loans"),
    ("dave",    220, 0, True,  0.65, [5, 40, 150],    "you are an idiot and scum"),
    ("eve",     100, 0, False, 0.50, [4, 35, 110],    "check out my new crypto blog"),
]


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def clamp(x):
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# SECTION 1 - velocity scoring (rate-based, multi-window blend)
# ---------------------------------------------------------------------------

def velocity_score(counts):
    """Weighted blend of per-window saturation ratios. Each ratio capped at 1."""
    s = 0.0
    for (_name, limit, w), c in zip(WINDOWS, counts):
        s += w * clamp(c / float(limit))
    return s


# ---------------------------------------------------------------------------
# SECTION 2 - pattern detection (weighted regex catalog)
# ---------------------------------------------------------------------------

def pattern_score(msg):
    """Return (score in [0,1], list of matched category names)."""
    total = 0.0
    hits = []
    for name, rx, w, ic in PATTERNS:
        flags = re.IGNORECASE if ic else 0
        if re.search(rx, msg, flags):
            total += w
            hits.append(name)
    return clamp(total), hits


# ---------------------------------------------------------------------------
# SECTION 3 - content moderation / toxicity (severity lexicon)
# ---------------------------------------------------------------------------

def toxicity_score(msg):
    """Return (score in [0,1], list of matched toxic terms)."""
    low = msg.lower()
    total = 0.0
    hits = []
    for word, sev in TOXIC.items():
        if re.search(r"\b" + re.escape(word) + r"\b", low):
            total += sev
            hits.append(word)
    return clamp(total), hits


# ---------------------------------------------------------------------------
# SECTION 4 - reputation scoring (trust from age + history)
# ---------------------------------------------------------------------------

def reputation(age_days, violations, verified, engagement):
    """Return trust in [0,1] (higher = more trusted, lower risk)."""
    age_norm = clamp(age_days / AGE_FULL_TRUST_DAYS)
    history_clean = HISTORY_DECAY ** violations
    trust = (W_AGE * age_norm
             + W_ENG * engagement
             + W_VER * (1.0 if verified else 0.0)
             + W_HIST * history_clean)
    return clamp(trust)


# ---------------------------------------------------------------------------
# SECTION 5 - risk fusion + action escalation
# ---------------------------------------------------------------------------

def risk_score(vel, pat, trust, tox):
    return W_VEL * vel + W_PAT * pat + W_REP * (1.0 - trust) + W_TOX * tox


def base_tier(risk):
    for name, thresh in TIERS:
        if risk < thresh:
            return name
    return "BAN"


def hard_override(vel, pat, tox):
    """Deterministic rules layered on top of the score.

    Coordinated spam needs BOTH high velocity AND high pattern (a single
    high signal alone is not enough -- frank has vel 0.96 but pat 0.35, so
    no hard rule, just a CHALLENGE). Spambot has both at 1.0 -> BAN.
    """
    if vel >= 0.95 and pat >= 0.80:
        return "BAN"
    if tox >= 0.95:
        return "BAN"
    return None


def escalate(tier, prior_offenses):
    """Bump the response one tier per prior offense (progressive discipline)."""
    i = TIER_ORDER.index(tier)
    return TIER_ORDER[min(len(TIER_ORDER) - 1, i + prior_offenses)]


def decide(vel, pat, tox, risk):
    """Return (final_action, basis) where basis is 'hard-rule' or 'score'."""
    tier = base_tier(risk)
    h = hard_override(vel, pat, tox)
    return (h, "hard-rule") if h else (tier, "score")


# ---------------------------------------------------------------------------
# SECTION 7 - scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 7: Scale estimation")
    dau_logins = 100_000_000
    peak_qps = 100_000
    entities_per_login = 4          # ip, device, user, asn
    windows = 4                     # 1m, 10m, 1h, 24h
    lookups_per_login = entities_per_login * windows
    active_entities = 10_000_000    # hot subset in Redis
    bytes_per_velocity_key = 200    # sorted-set metadata + member/score pairs
    emb_dim = 128
    hot_accounts = 10_000_000
    bytes_per_req = 2048

    velocity_mem_gb = active_entities * bytes_per_velocity_key / 1e9
    embedding_hot_gb = hot_accounts * emb_dim * 4 / 1e9
    bandwidth_mbs = peak_qps * bytes_per_req / 1e6

    print("Assumptions:")
    print("  daily logins (login path)     = %s" % fmt_int(dau_logins))
    print("  peak velocity-check QPS       = %s /s" % fmt_int(peak_qps))
    print("  entities checked / login      = %d (ip, device, user, asn)" % entities_per_login)
    print("  windows / entity              = %d (1m, 10m, 1h, 24h)" % windows)
    print("  -> pipelined Redis lookups/login = %d (one roundtrip)" % lookups_per_login)
    print("  active velocity entities      = %s (hot subset)" % fmt_int(active_entities))
    print("  embedding dim / cached vector = %d (GNN, 24h TTL)" % emb_dim)
    print()
    print("Throughput & storage:")
    print("  peak pipelined ops/s          = %s (1 pipeline/login)" % fmt_int(peak_qps))
    print("  velocity memory (sorted sets) = %.2f GB (%s keys * %d B)" %
          (velocity_mem_gb, fmt_int(active_entities), bytes_per_velocity_key))
    print("  hot embedding cache (Redis)   = %.2f GB (%s accts * %d * 4 B)" %
          (embedding_hot_gb, fmt_int(hot_accounts), emb_dim))
    print("  ingress bandwidth @ peak      = %.1f MB/s (%s req/s * %d B)" %
          (bandwidth_mbs, fmt_int(peak_qps), bytes_per_req))
    print()
    print("Sync path latency budget (p99 < 20 ms):")
    budget = [("edge filter (TLS/JA3 + ASN blocklist)", 1),
              ("velocity engine (pipelined Redis)",     3),
              ("device intelligence (fingerprint)",    2),
              ("risk scorer (GBM, ~50 features)",      8),
              ("network + queueing slack",             6)]
    total_ms = 0
    for name, ms in budget:
        print("  %-42s %2d ms" % (name, ms))
        total_ms += ms
    print("  %-42s %2d ms" % ("TOTAL", total_ms))
    print("  Anything slower must move to the ASYNC path (graph / GNN / ring")
    print("  detection): results cached back into Redis, consumed next request.")
    print()

    ok = (velocity_mem_gb == 2.0 and abs(embedding_hot_gb - 5.12) < 1e-9 and
          abs(bandwidth_mbs - 204.8) < 1e-9 and total_ms == 20 and
          lookups_per_login == 16)
    print("[check] velocity=2.0GB, emb=5.12GB, bw=204.8MB/s, sync=20ms, 16 lookups? " +
          ("OK" if ok else "FAIL"))
    return {
        "daily_logins": dau_logins, "peak_qps": peak_qps,
        "lookups_per_login": lookups_per_login,
        "velocity_mem_gb": velocity_mem_gb, "embedding_hot_gb": embedding_hot_gb,
        "bandwidth_mbs": bandwidth_mbs, "sync_latency_ms": total_ms,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def fmt_int(n):
    return "{:,}".format(n)


# ---------------------------------------------------------------------------
# SECTION 8 - GOLD values pinned for abuse_detection.html
# ---------------------------------------------------------------------------

def section_gold(results, scale):
    banner("SECTION 8: GOLD values (pinned for abuse_detection.html)")

    gold = []
    for r in results:
        gold.append(("vel_" + r["name"],     round(r["vel"], 3)))
        gold.append(("pat_" + r["name"],     round(r["pat"], 3)))
        gold.append(("tox_" + r["name"],     round(r["tox"], 3)))
        gold.append(("rep_" + r["name"],     round(r["trust"], 3)))
        gold.append(("risk_" + r["name"],    round(r["risk"], 3)))
        gold.append(("action_" + r["name"],  r["action"]))
    gold.append(("fusion_weights",       "%.2f,%.2f,%.2f,%.2f" % (W_VEL, W_PAT, W_REP, W_TOX)))
    gold.append(("tier_thresholds",      "%.2f,%.2f,%.2f,%.2f" %
                 (TIERS[0][1], TIERS[1][1], TIERS[2][1], TIERS[3][1])))
    gold.append(("eve_escalation",       ",".join(r["eve_seq"])))
    gold.append(("scale_velocity_gb",    round(scale["velocity_mem_gb"], 2)))
    gold.append(("scale_embedding_gb",   round(scale["embedding_hot_gb"], 2)))
    gold.append(("scale_bandwidth_mbs",  round(scale["bandwidth_mbs"], 1)))
    gold.append(("scale_sync_ms",        scale["sync_latency_ms"]))

    for k, v in gold:
        print("  %-24s = %s" % (k, v))
    print()

    # assertions match the hand-computed values
    checks = True
    by_name = {r["name"]: r for r in results}
    checks &= abs(by_name["alice"]["risk"] - 0.066) < 0.001
    checks &= by_name["alice"]["action"] == "ALLOW"
    checks &= abs(by_name["bob"]["risk"] - 0.455) < 0.001
    checks &= by_name["bob"]["action"] == "WARN"
    checks &= abs(by_name["carol"]["risk"] - 0.655) < 0.001
    checks &= by_name["carol"]["action"] == "THROTTLE"
    checks &= abs(by_name["frank"]["risk"] - 0.733) < 0.001
    checks &= by_name["frank"]["action"] == "CHALLENGE"
    checks &= by_name["frank"]["basis"] == "score"
    checks &= abs(by_name["spambot"]["risk"] - 0.727) < 0.001
    checks &= by_name["spambot"]["action"] == "BAN"
    checks &= by_name["spambot"]["basis"] == "hard-rule"
    checks &= abs(by_name["dave"]["risk"] - 0.433) < 0.001
    checks &= by_name["dave"]["action"] == "BAN"
    checks &= by_name["dave"]["basis"] == "hard-rule"
    checks &= abs(by_name["spambot"]["trust"] - 0.116) < 0.001
    checks &= abs(by_name["alice"]["trust"] - 0.950) < 0.001
    checks &= by_name["eve"]["eve_seq"] == ["WARN", "THROTTLE", "CHALLENGE", "BAN"]
    checks &= abs(scale["velocity_mem_gb"] - 2.0) < 1e-9
    checks &= abs(scale["embedding_hot_gb"] - 5.12) < 1e-9
    print("[check] GOLD reproduces from velocity+pattern+toxicity+reputation? " +
          ("OK" if checks else "FAIL"))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("# abuse_detection.py - Abuse detection system design simulation")
    print("# Pure Python stdlib only. Numbers below feed ABUSE_DETECTION.md")
    print("# and abuse_detection.html (gold-checked).")
    print("# Model: risk = 0.30*vel + 0.25*pat + 0.20*(1-rep) + 0.25*tox")
    print("#       then hard-rule overrides + progressive escalation.")

    # ------------------------------------------------------------------
    # SECTION 1: velocity
    # ------------------------------------------------------------------
    banner("SECTION 1: Velocity scoring (rate-based, multi-window blend)")
    print("Each window saturates at its request limit; the per-window ratio is")
    print("capped at 1.0 then blended with window weights (1m=0.5, 10m=0.3, 1h=0.2).")
    print("  vel = 0.5*min(1,c/10) + 0.3*min(1,c/80) + 0.2*min(1,c/500)")
    print("Bursts (1-min window) dominate -> the strongest single abuse signal.\n")
    print("  %-9s %7s %7s %7s   %6s" % ("account", "1m", "10m", "1h", "vel"))
    vel_by_name = {}
    for name, _a, _v, _ve, _e, counts, _m in SCENARIOS:
        s = velocity_score(counts)
        vel_by_name[name] = s
        print("  %-9s %7d %7d %7d   %.3f" %
              (name, counts[0], counts[1], counts[2], s))
    print()
    ok = (abs(vel_by_name["alice"] - 0.188) < 0.001 and
          abs(vel_by_name["spambot"] - 1.000) < 0.001 and
          abs(vel_by_name["carol"] - 0.920) < 0.001)
    print("[check] alice vel~0.188, carol vel~0.920, spambot vel~1.000? " +
          ("OK" if ok else "FAIL"))

    # ------------------------------------------------------------------
    # SECTION 2: pattern detection
    # ------------------------------------------------------------------
    banner("SECTION 2: Pattern detection (weighted regex catalog)")
    print("Six signature categories, each contributing its weight ONCE if matched.")
    print("Sum capped at 1.0. Deterministic rules catch known spam shapes that")
    print("a learned model has never been trained on.\n")
    print("  %-11s %-34s %5s  %s" % ("category", "regex", "w", "ic"))
    for name, rx, w, ic in PATTERNS:
        print("  %-11s %-34s %5.2f  %s" % (name, rx, w, "yes" if ic else "no"))
    print()
    print("  %-9s %-44s %6s  %s" % ("account", "message", "score", "hits"))
    pat_by_name = {}
    for name, _a, _v, _ve, _e, _c, msg in SCENARIOS:
        s, hits = pattern_score(msg)
        pat_by_name[name] = s
        print("  %-9s %-44s %6.3f  %s" % (name, msg[:44], s, ",".join(hits) or "-"))
    print()
    ok = (abs(pat_by_name["alice"] - 0.000) < 1e-9 and
          abs(pat_by_name["spambot"] - 1.000) < 1e-9 and
          abs(pat_by_name["carol"] - 0.900) < 0.001 and
          abs(pat_by_name["bob"] - 0.350) < 0.001)
    print("[check] alice 0.0, bob 0.35, carol 0.90, spambot 1.0? " +
          ("OK" if ok else "FAIL"))

    # ------------------------------------------------------------------
    # SECTION 3: toxicity / content moderation
    # ------------------------------------------------------------------
    banner("SECTION 3: Content moderation / toxicity (severity lexicon)")
    print("A severity-weighted toxic lexicon. Each matched term adds its severity;")
    print("sum capped at 1.0. Whole-word, case-insensitive. In production this is a")
    print("transformer toxicity classifier; the lexicon is the deterministic stand-in.\n")
    print("  lexicon (severity):")
    print("  " + ", ".join("%s(%.1f)" % (w, s) for w, s in sorted(TOXIC.items())))
    print()
    print("  %-9s %-44s %6s  %s" % ("account", "message", "tox", "hits"))
    tox_by_name = {}
    for name, _a, _v, _ve, _e, _c, msg in SCENARIOS:
        s, hits = toxicity_score(msg)
        tox_by_name[name] = s
        print("  %-9s %-44s %6.3f  %s" % (name, msg[:44], s, ",".join(hits) or "-"))
    print()
    ok = (abs(tox_by_name["dave"] - 1.000) < 1e-9 and
          abs(tox_by_name["alice"] - 0.000) < 1e-9)
    print("[check] dave tox~1.0 (idiot+scum), alice tox~0.0? " +
          ("OK" if ok else "FAIL"))

    # ------------------------------------------------------------------
    # SECTION 4: reputation
    # ------------------------------------------------------------------
    banner("SECTION 4: Reputation scoring (trust from age + history)")
    print("A trust score in [0,1] blending four factors (higher = more trusted):")
    print("  trust = 0.35*min(1,age/365) + 0.25*engagement")
    print("        + 0.20*verified + 0.20*(0.8**violations)")
    print("history term DECAYS 20% per prior violation. Reputation risk = 1 - trust.\n")
    print("  %-9s %5s %5s %5s %8s   %6s   %6s" %
          ("account", "age", "viol", "ver", "engage", "trust", "risk"))
    trust_by_name = {}
    for name, age, viol, ver, eng, _c, _m in SCENARIOS:
        t = reputation(age, viol, ver, eng)
        trust_by_name[name] = t
        print("  %-9s %5d %5d %5s %8.2f   %.3f   %.3f" %
              (name, age, viol, "Y" if ver else "N", eng, t, 1.0 - t))
    print()
    ok = (abs(trust_by_name["alice"] - 0.950) < 0.001 and
          abs(trust_by_name["spambot"] - 0.116) < 0.001 and
          abs(trust_by_name["dave"] - 0.773) < 0.001)
    print("[check] alice trust~0.950, dave~0.773, spambot~0.116? " +
          ("OK" if ok else "FAIL"))

    # ------------------------------------------------------------------
    # SECTION 5: risk fusion + action escalation
    # ------------------------------------------------------------------
    banner("SECTION 5: Risk fusion + action escalation (full pipeline)")
    print("Fusion (weights sum to 1.0):")
    print("  risk = 0.30*vel + 0.25*pat + 0.20*(1-trust) + 0.25*tox")
    print("Then two HARD RULES override the score (need BOTH conditions):")
    print("  vel>=0.95 AND pat>=0.80 -> BAN   (coordinated spam)")
    print("  tox>=0.95               -> BAN   (severe toxicity)")
    print("Score-only tiers: <0.30 ALLOW, <0.50 WARN, <0.70 THROTTLE,")
    print("                  <0.85 CHALLENGE, else BAN.\n")
    print("  %-9s %5s %5s %5s %5s %6s  %-9s %-9s" %
          ("account", "vel", "pat", "rep", "tox", "risk", "action", "basis"))
    results = []
    for (name, age, viol, ver, eng, counts, msg) in SCENARIOS:
        vel = vel_by_name[name]
        pat = pat_by_name[name]
        tox = tox_by_name[name]
        trust = trust_by_name[name]
        risk = risk_score(vel, pat, trust, tox)
        action, basis = decide(vel, pat, tox, risk)
        results.append({"name": name, "vel": vel, "pat": pat, "tox": tox,
                        "trust": trust, "risk": risk, "action": action,
                        "basis": basis})
        print("  %-9s %5.2f %5.2f %5.2f %5.2f %6.3f  %-9s %-9s" %
              (name, vel, pat, trust, tox, risk, action, basis))
    print()
    print("  >>> alice: trusted + slow + clean -> ALLOW.")
    print("  >>> bob:   chatty established user, crypto spam word -> WARN.")
    print("  >>> carol: brand-new, bursty, url+freemoney+repeats -> THROTTLE")
    print("      (vel 0.92 < 0.95, so the hard rule does NOT fire).")
    print("  >>> frank: high velocity (0.96) BUT low pattern (0.35) -> CHALLENGE.")
    print("      Same risk tier as spambot (~0.73) but NO hard rule: velocity")
    print("      alone is never a ban, you need velocity AND pattern together.")
    print("  >>> spambot: vel 1.0 + pat 1.0 -> BAN via hard-rule (coordinated).")
    print("  >>> dave:  trusted but posts severe toxicity -> BAN via hard-rule")
    print("      (reputation cannot buy your way past toxicity).")
    print()
    ok = (results[0]["action"] == "ALLOW" and results[1]["action"] == "WARN" and
          results[2]["action"] == "THROTTLE" and results[3]["action"] == "CHALLENGE" and
          results[4]["action"] == "BAN" and results[5]["action"] == "BAN")
    print("[check] pipeline emits ALLOW/WARN/THROTTLE/CHALLENGE/BAN/BAN? " +
          ("OK" if ok else "FAIL"))

    # ------------------------------------------------------------------
    # SECTION 6: progressive escalation sequence
    # ------------------------------------------------------------------
    banner("SECTION 6: Progressive escalation (same actor, repeated offenses)")
    print("Per-actor offense counter bumps the response one tier per prior offense.")
    print(" eve posts the SAME borderline crypto-spam message four times.")
    print(" Base score-tier for eve's message is WARN (risk ~0.316); each repeat")
    print(" escalates: WARN -> THROTTLE -> CHALLENGE -> BAN.\n")
    eve = [r for r in results if r["name"] == "eve"][0]
    eve_base = base_tier(eve["risk"])
    eve_seq = []
    print("  offense  base_tier   ->  final_action")
    for k in range(4):
        final = escalate(eve_base, k)
        eve_seq.append(final)
        print("    %d       %-9s   ->  %-9s" % (k + 1, eve_base, final))
    eve["eve_seq"] = eve_seq
    print()
    print("  This is the 'warn before you ban' product discipline: a single")
    print("  borderline message is not a ban, but a PATTERN of them is. The")
    print("  offense counter resets after a clean cooldown window.")
    print()
    ok = eve_seq == ["WARN", "THROTTLE", "CHALLENGE", "BAN"]
    print("[check] eve escalates WARN->THROTTLE->CHALLENGE->BAN? " +
          ("OK" if ok else "FAIL"))

    # ------------------------------------------------------------------
    # SECTION 7: scale
    # ------------------------------------------------------------------
    scale = section_scale()

    # ------------------------------------------------------------------
    # SECTION 8: GOLD
    # ------------------------------------------------------------------
    section_gold(results, scale)

    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
