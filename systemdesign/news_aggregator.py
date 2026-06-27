"""
news_aggregator.py - Reference simulation of a News Aggregator (Google News /
Techmeme / Flipboard style): pull news from many RSS/Atom sources, deduplicate
near-identical articles with SimHash, rank by recency + source authority +
relevance, schedule polling adaptively, and generate personalised feeds.

This is the single source of truth for NEWS_AGGREGATOR.md and
news_aggregator.html. Every hamming distance, ranking score, poll interval, and
scale number in the guide is printed by this file. Deterministic (no
randomness, no wall-clock). Re-run reproduces every value.

Run:
    python3 news_aggregator.py

========================================================================
THE INTUITION (read this first) - the wire desk
========================================================================
A news aggregator is a newspaper wire desk. Hundreds of thousands of publishers
each emit a stream of articles via RSS/Atom feeds. Your job is to fetch every
feed often enough to be FRESH, but not so often that you hammer the publishers;
collapse the 20 near-identical copies of "the AP ran a story" into ONE article;
and rank the survivors so each reader sees the stories that matter TO THEM. The
hard parts are all about MERGING many noisy streams into one clean, ranked list:

  * POLLING (fetch -> parse -> extract):
      Periodically HTTP GET each feed, parse the XML, extract
      (title, url, published_at, summary, body). Use conditional GET
      (If-Modified-Since / If-None-Match ETag) so an UNCHANGED feed answers
      "304 Not Modified" in ~0.5 KB instead of re-downloading the full ~250 KB.
      Politeness: respect <ttl> / <sy:updatePeriod> and per-domain rate limits.

  * DEDUPLICATION (SimHash + content fingerprint):
      The same story is published by 20 outlets (wire copy, syndication,
      scraping). Exact URL canonicalization catches mirrors; a content
      fingerprint (SimHash, 64-bit) catches NEAR-duplicates - lightly rewritten
      copies. Two SimHash fingerprints with a small HAMMING DISTANCE (<= 3 bits)
      are treated as the same story. At scale, band the fingerprints with LSH so
      you only compare articles in the same bucket (O(n) instead of O(n^2)).

  * RANKING (recency + source authority + relevance):
      score = w_rec * recency(age) + w_auth * authority(source)
                    + w_rel * relevance(article, reader)
        recency   : exponential decay (news goes stale FAST; half-life ~6h).
        authority : [0,1] per source (Reuters 0.95, a random blog 0.30) -
                    credibility / editorial weight.
        relevance : overlap of the article's topics with the reader's interest
                    profile. The signal that makes the feed PERSONAL.

  * CRAWL SCHEDULING (adaptive poll interval):
      A wire that publishes 120x/day must be polled far more often than a blog
      that publishes 1x/day. Set each feed's poll interval inversely proportional
      to its observed update rate (poll ~2x the update rate to stay fresh), with
      min/max clamps. Back off exponentially on feeds that stop updating. This
      cuts total polls (and bandwidth) by ~80% vs the naive "poll everything
      every 15 minutes".

  * PERSONALISED FEED GENERATION:
      Merge candidates from the reader's subscribed sources, dedup, score each
      against the reader's interest profile, sort desc, return top-K. The SAME
      candidate pool ranks differently for a tech enthusiast vs a finance reader.

The NON-OBVIOUS parts this file drills into:
  1. SimHash is order-invariant: shuffling a sentence's words barely changes the
     fingerprint, because it sums per-bit votes across ALL tokens. That is WHY it
     catches near-dups that edit a few words. (Section B)
  2. Near-dup != exact-dup: exact copies collapse by URL canonicalization or a
     plain SHA of the body; SimHash is specifically for REWRITES, where a few
     tokens differ. (Section B)
  3. Authority can beat recency AND relevance can beat authority: a 5h-old
     Reuters fed-rate story still outranks a fresh no-name blog post for a
     finance reader because authority+relevance dominate the decay. (Section C)
  4. Adaptive polling is bandwidth: polling a daily blog every 15 min wastes 95%
     of fetches on 304s; scheduling by update rate + conditional GET removes the
     waste. (Section D)
  5. Personalization REORDERS the same pool: two readers see different top-3
     from identical candidates because the relevance term differs. (Section E)

========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
========================================================================
  RSS / Atom feed  : an XML file a publisher updates with their latest items.
                     Polling = HTTP GETting it on a schedule.
  item             : one entry in a feed (<item> / <entry>): title, link, date.
  conditional GET  : send If-Modified-Since / If-None-Match (ETag); server
                     replies 304 (tiny) if unchanged, 200 (full body) if changed.
  canonical URL    : normalized form (lowercase host, strip www, sorted params,
                     drop fragment) so mirror URLs collapse to one string.
  SimHash          : a 64-bit near-duplicate fingerprint of text. Built by
                     hashing each token, then per-bit majority vote weighted by
                     token frequency.
  hamming distance : number of differing bits between two fingerprints.
                     Small (<=3) => near-duplicate; large (>=20) => different.
  LSH banding      : split a 64-bit fingerprint into bands; only compare items
                     that share a band. Turns O(n^2) dedup into ~O(n).
  recency / decay  : time discount. decay(age) = 0.5 ** (age / half_life).
                     News half-life is short (~6h) - stale fast.
  authority        : [0,1] credibility score per source.
  relevance        : [0,1] topic overlap between article and reader interests.
  poll interval    : minutes between two fetches of the same feed.
  update rate      : observed new articles per day for a feed.
========================================================================
"""

import hashlib
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


# =========================================================================
# Component 1: FNV-1a 64-bit hash + tokenizer (identical in news_aggregator.html)
# =========================================================================
# We use FNV-1a (not md5) so the .html gold-check - which has no crypto libs -
# can reproduce EXACTLY the same fingerprint bit-for-bit. Pure, dependency-free,
# identical in Python and JavaScript.
# =========================================================================
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK64 = 0xFFFFFFFFFFFFFFFF


def fnv1a_64(text):
    """64-bit FNV-1a hash of an ASCII string. Matches the JS implementation."""
    h = FNV_OFFSET
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * FNV_PRIME) & MASK64
    return h


def tokenize(text):
    """Lowercase alphanumeric tokens. Identical to JS /[a-z0-9]+/g."""
    return re.findall(r"[a-z0-9]+", text.lower())


def popcount(n):
    return bin(n).count("1")


def simhash(text, bits=64):
    """
    64-bit SimHash fingerprint.

    Algorithm (Charikar 2002):
      1. tokenize text -> features
      2. hash each feature to 64 bits (FNV-1a)
      3. for each of 64 bit positions, sum +1 if the bit is set, -1 if not
         (weighted by token frequency)
      4. fingerprint bit i = 1 if the per-position sum > 0, else 0

    Order-invariant: shuffling tokens barely changes the result because every
    token contributes to every bit's majority vote.
    """
    tokens = tokenize(text)
    if not tokens:
        return 0
    v = [0] * bits
    for tok in tokens:
        h = fnv1a_64(tok)
        for i in range(bits):
            if (h >> i) & 1:
                v[i] += 1
            else:
                v[i] -= 1
    fp = 0
    for i in range(bits):
        if v[i] > 0:
            fp |= (1 << i)
    return fp


def hamming(a, b):
    """Number of differing bits between two fingerprints."""
    return popcount(a ^ b)


DUP_THRESHOLD = 3   # hamming <= 3 over 64 bits => near-duplicate (industry rule of thumb)


def is_near_duplicate(text_a, text_b, threshold=DUP_THRESHOLD):
    return hamming(simhash(text_a), simhash(text_b)) <= threshold


# =========================================================================
# Component 2: URL canonicalization (catches exact mirror copies)
# =========================================================================
def canonicalize_url(url):
    """Normalize: https, lowercase host, strip 'www.', drop trailing '/', sort
    query params, drop fragment. Mirrors collapse to one canonical string."""
    p = urlparse(url)
    scheme = "https"
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    host = netloc.split(":")[0]
    path = p.path.rstrip("/") or "/"
    params = sorted(parse_qsl(p.query, keep_blank_values=True))
    query = urlencode(params)
    return urlunparse((scheme, host, path, "", query, ""))


# =========================================================================
# Component 3: Article + Feed models
# =========================================================================
class Article:
    """A deduplicated news article entering the ranking pipeline."""
    def __init__(self, aid, source, authority, age_hours, topics, title, body):
        self.id = aid
        self.source = source
        self.authority = authority          # [0,1] credibility of the source
        self.age_hours = age_hours
        self.topics = set(topics)           # category / keyword tags
        self.title = title
        self.body = body

    def __repr__(self):
        return f"Article({self.id}, {self.source}, age={self.age_hours}h)"


# =========================================================================
# Component 4: Ranking primitives (recency + authority + relevance)
# =========================================================================
HALF_LIFE_HOURS = 6.0      # news decays fast: worth half its score every 6h
W_RECENCY = 0.45
W_AUTHORITY = 0.25
W_RELEVANCE = 0.30


def recency(age_hours, half_life=HALF_LIFE_HOURS):
    """Exponential decay: 1.0 at age=0, 0.5 at age=half_life."""
    return 0.5 ** (age_hours / half_life)


def relevance(article_topics, interests):
    """Mean interest weight over the article's topics, in [0,1].
    A story tagged {ai, openai, chips} for a reader who cares about AI scores
    high; a {fed, rates} story for the same reader scores low."""
    if not article_topics:
        return 0.0
    return sum(interests.get(t, 0.0) for t in article_topics) / len(article_topics)


def rank_score(article, interests,
               w_rec=W_RECENCY, w_auth=W_AUTHORITY, w_rel=W_RELEVANCE,
               half_life=HALF_LIFE_HOURS):
    """Weighted sum: recency + authority + relevance. Weights sum to 1.0."""
    rec = recency(article.age_hours, half_life)
    auth = article.authority
    rel = relevance(article.topics, interests)
    return rec, auth, rel, w_rec * rec + w_auth * auth + w_rel * rel


# =========================================================================
# Component 5: Adaptive crawl scheduling
# =========================================================================
MIN_INTERVAL = 15.0          # minutes - never poll faster than every 15 min
MAX_INTERVAL = 1440.0        # minutes - never slower than once a day
SAFETY = 0.5                 # poll at half the inter-update gap (~2x update rate)
MINUTES_PER_DAY = 1440.0


def target_interval(updates_per_day, safety=SAFETY,
                    min_i=MIN_INTERVAL, max_i=MAX_INTERVAL):
    """Poll interval (minutes) inversely proportional to update rate.
    raw = (minutes_per_day / updates_per_day) * safety, clamped to [min_i, max_i].
    A feed updating 48x/day -> poll every 15 min; a daily blog -> once a day."""
    raw = (MINUTES_PER_DAY / updates_per_day) * safety
    return max(min_i, min(max_i, raw))


def polls_per_day(interval_min):
    return MINUTES_PER_DAY / interval_min


# =========================================================================
# Banner helper
# =========================================================================
def banner(title):
    line = "=" * 72
    print()
    print(line)
    print(" " + title)
    print(line)


# =========================================================================
# Deterministic candidate pool (Sections C, E). Six articles, mixed signals.
# =========================================================================
SOURCES = {
    "Reuters":   0.95,
    "Bloomberg": 0.90,
    "Wired":     0.70,
    "TechBlog":  0.50,
    "BlogSpot":  0.30,
}

CANDIDATES = [
    Article("a1", "Reuters",   0.95, 1.0, {"ai", "openai", "gpt5"},
            "OpenAI launches GPT-5",
            "OpenAI announces GPT-5 model with improved reasoning and "
            "multimodal capabilities at the developer conference"),
    Article("a2", "TechBlog",  0.50, 2.0, {"ai", "openai", "llm"},
            "GPT-5 deep dive",
            "A hands on look at the new GPT-5 large language model from OpenAI "
            "and what it means for developers"),
    Article("a3", "Bloomberg", 0.90, 5.0, {"fed", "rates", "economy"},
            "Fed holds rates steady",
            "The Federal Reserve kept interest rates unchanged as inflation "
            "cools and the broader economy remains stable"),
    Article("a4", "BlogSpot",  0.30, 0.5, {"ai", "startup", "funding"},
            "AI startup raises Series B",
            "A small AI startup closed a large series B funding round to build "
            "open source reasoning models"),
    Article("a5", "Reuters",   0.95, 10.0, {"fed", "inflation"},
            "Inflation eases to 3 percent",
            "New data shows consumer price inflation eased to three percent "
            "raising hopes of future rate cuts"),
    Article("a6", "Wired",     0.70, 3.0, {"ai", "openai", "chips"},
            "OpenAI orders custom silicon",
            "OpenAI contracted a chipmaker for custom silicon to power the next "
            "generation of large language models"),
]

# Two readers with very different interest profiles.
INTERESTS_TECH = {
    "ai": 0.9, "openai": 0.8, "llm": 0.6, "chips": 0.4,
    "fed": 0.1, "rates": 0.1, "economy": 0.1, "inflation": 0.1,
    "startup": 0.3, "funding": 0.3, "gpt5": 0.0,
}
INTERESTS_FINANCE = {
    "ai": 0.1, "openai": 0.1, "llm": 0.1, "chips": 0.1,
    "fed": 0.9, "rates": 0.8, "economy": 0.8, "inflation": 0.7,
    "startup": 0.1, "funding": 0.1, "gpt5": 0.0,
}


# =========================================================================
# Main simulation
# =========================================================================
def main():
    banner("NEWS AGGREGATOR - reference simulation")
    print("Source of truth for NEWS_AGGREGATOR.md and news_aggregator.html.")
    print("All numbers below are deterministic; re-run reproduces them.")

    # =====================================================================
    # SECTION A: RSS/ATOM POLLING (fetch -> parse -> extract) + conditional GET
    # =====================================================================
    banner("Section A - RSS/Atom polling (fetch -> parse -> extract)")
    print("Periodically GET each feed, parse the XML items, extract fields. Use")
    print("conditional GET (If-None-Match ETag): if the stored ETag matches, the")
    print("server replies 304 Not Modified (~0.5 KB) and we SKIP parsing.\n")

    FEED_SIZE_KB = 250.0        # a full feed body
    NOT_MODIFIED_KB = 0.5       # a 304 response (headers only)

    # Two simulated raw feeds: list of dicts already "fetched".
    feeds = [
        {"id": "feed_tech", "etag": "etag-2024-11", "items": [
            {"title": "OpenAI launches GPT-5",
             "url": "https://www.wired.com/story/openai-gpt5",
             "published_at": "2024-11-01T09:00Z",
             "summary": "OpenAI announces a new multimodal model"},
            {"title": "Custom silicon for AI",
             "url": "https://www.wired.com/story/ai-custom-silicon",
             "published_at": "2024-11-01T08:00Z",
             "summary": "AI firms order bespoke chips"},
        ]},
        {"id": "feed_blog", "etag": "etag-2024-10", "items": []},
    ]

    stored_etags = {"feed_tech": "etag-2024-10", "feed_blog": "etag-2024-10"}

    def fetch_feed(feed):
        """Conditional GET. Returns (status, bytes_kb, items)."""
        if feed["etag"] == stored_etags.get(feed["id"]):
            return 304, NOT_MODIFIED_KB, []   # unchanged -> skip
        return 200, FEED_SIZE_KB, feed["items"]

    def parse_item(item):
        """Extract normalized fields from a raw RSS <item>."""
        return {
            "title": item["title"],
            "url": canonicalize_url(item["url"]),
            "published_at": item["published_at"],
            "summary": item["summary"],
        }

    total_kb = 0.0
    extracted = []
    for feed in feeds:
        status, kb, items = fetch_feed(feed)
        total_kb += kb
        etag = stored_etags[feed['id']]
        print(f"  GET {feed['id']:12s}  stored ETag={etag}")
        print(f"      -> HTTP {status}  ({kb:.1f} KB)"
              + ("  [unchanged: skip parse]" if status == 304 else ""))
        if status == 200:
            for it in items:
                parsed = parse_item(it)
                extracted.append(parsed)
                print(f"      parsed: {parsed['title']}")
                print(f"               url={parsed['url']}")

    full_fetch_kb = len(feeds) * FEED_SIZE_KB
    saved = full_fetch_kb - total_kb
    print(f"\n  Bandwidth: naive full-fetch = {full_fetch_kb:.0f} KB, "
          f"conditional GET = {total_kb:.1f} KB  (saved {saved:.1f} KB, "
          f"{saved/full_fetch_kb*100:.0f}%)")
    print(f"  Extracted {len(extracted)} article(s) from "
          f"{sum(1 for f in feeds if fetch_feed(f)[0]==200)} changed feed(s).")
    print("\n  >>> Conditional GET skips unchanged feeds (304), so the polling")
    print("      cost is dominated by feeds that ACTUALLY changed - a big win")
    print("      when most feeds are quiet most of the time.")

    # =====================================================================
    # SECTION B: DEDUPLICATION (URL canonicalization + SimHash)
    # =====================================================================
    banner("Section B - Deduplication (URL canonicalization + SimHash)")

    print("Layer 1: URL canonicalization - mirror URLs collapse to one string.\n")
    url_variants = [
        "https://WWW.Wired.com/story/gpt5?ref=rss&ut=1",
        "https://wired.com/story/gpt5/?ut=1&ref=rss#top",
        "https://wired.com/story/gpt5?ref=rss&ut=1",
        "http://wired.com:80/story/gpt5/?ref=rss&ut=1",
    ]
    canon_set = set()
    for v in url_variants:
        c = canonicalize_url(v)
        canon_set.add(c)
        print(f"  {v:48s} -> {c}")
    print(f"\n  {len(url_variants)} variant URLs -> {len(canon_set)} canonical URL(s)"
          f"  (dedup rate "
          f"{(len(url_variants)-len(canon_set))/len(url_variants)*100:.0f}%)")

    print("\nLayer 2: SimHash (near-duplicate fingerprint, 64-bit).\n")
    body_exact = (
        "OpenAI has officially announced the GPT-5 model featuring significantly "
        "improved reasoning capabilities and expanded multimodal support at its "
        "annual developer conference in San Francisco. The new model demonstrates "
        "substantial gains in code generation mathematical problem solving and "
        "tool use according to early benchmarks shared by the company. Chief "
        "executive Sam Altman described the release as a major step toward more "
        "reliable and useful artificial intelligence systems for everyday "
        "consumers and enterprise developers alike.")
    body_near = (
        "OpenAI has officially announced the GPT-5 model featuring significantly "
        "enhanced reasoning capabilities and expanded multimodal support at its "
        "annual developer conference in San Francisco. The new model demonstrates "
        "substantial gains in code generation mathematical problem solving and "
        "tool use according to early benchmarks shared by the company. Chief "
        "executive Sam Altman called the release a major step toward more "
        "reliable and useful artificial intelligence systems for everyday "
        "consumers and enterprise developers alike.")
    body_diff = (
        "The Federal Reserve voted to keep its benchmark interest rate "
        "unchanged this month as policymakers weigh cooling inflation against a "
        "still resilient labor market. Officials signaled that any future rate "
        "cuts would depend on additional evidence that price pressures are "
        "sustainably returning to the central bank two percent target. Treasury "
        "yields slipped and equity markets rallied following the announcement as "
        "investors reassessed the outlook for monetary policy.")

    fp_exact = simhash(body_exact)
    fp_near = simhash(body_near)
    fp_diff = simhash(body_diff)
    d_self = hamming(fp_exact, simhash(body_exact))
    d_near = hamming(fp_exact, fp_near)
    d_diff = hamming(fp_exact, fp_diff)

    print(f"  DUP_THRESHOLD = {DUP_THRESHOLD} bits (over 64) => near-duplicate")
    print(f"  body_exact fingerprint = {fp_exact:#018x}")
    print(f"  body_near  fingerprint = {fp_near:#018x}")
    print(f"  body_diff  fingerprint = {fp_diff:#018x}\n")
    print(f"  hamming(exact, exact_copy) = {d_self:>2}  -> duplicate? "
          f"{'YES' if d_self <= DUP_THRESHOLD else 'no'}")
    print(f"  hamming(exact, near_rewrite) = {d_near:>2}  -> duplicate? "
          f"{'YES' if d_near <= DUP_THRESHOLD else 'no'}  "
          f"(lightly rewritten copy, same story)")
    print(f"  hamming(exact, different_story) = {d_diff:>2}  -> duplicate? "
          f"{'YES' if d_diff <= DUP_THRESHOLD else 'no'}  "
          f"(different vocabulary)")
    print()
    print("  >>> SimHash catches REWRITES that exact hashing misses: 2 changed")
    print("      words barely move the fingerprint (small hamming), while a")
    print("      totally different story flips ~half the bits.")

    print("\nLayer 3: LSH banding (scale dedup from O(n^2) to ~O(n)).\n")
    bands = 4
    band_size = 64 // bands
    buckets_exact = [(fp_exact >> (b * band_size)) & ((1 << band_size) - 1) for b in range(bands)]
    buckets_near = [(fp_near >> (b * band_size)) & ((1 << band_size) - 1) for b in range(bands)]
    buckets_diff = [(fp_diff >> (b * band_size)) & ((1 << band_size) - 1) for b in range(bands)]
    shared_near = sum(1 for x, y in zip(buckets_exact, buckets_near) if x == y)
    shared_diff = sum(1 for x, y in zip(buckets_exact, buckets_diff) if x == y)
    print(f"  Split 64-bit fp into {bands} bands x {band_size} bits. Two articles")
    print(f"  are a CANDIDATE PAIR only if they share >=1 band (LSH property).\n")
    print(f"  bands shared (exact vs near_rewrite) = {shared_near}/{bands}  "
          f"-> candidate pair? {'YES' if shared_near >= 1 else 'no'}")
    print(f"  bands shared (exact vs different_story) = {shared_diff}/{bands}  "
          f"-> candidate pair? {'YES' if shared_diff >= 1 else 'no'}")
    print("\n  >>> Banding means we only run full hamming on items sharing a")
    print("      bucket - O(n) candidate pairs instead of O(n^2) all-pairs.")

    # =====================================================================
    # SECTION C: RANKING (recency + source authority + relevance)
    # =====================================================================
    banner("Section C - Ranking (recency + authority + relevance)")
    print(f"score = {W_RECENCY}*recency + {W_AUTHORITY}*authority + "
          f"{W_RELEVANCE}*relevance   (weights sum to "
          f"{W_RECENCY+W_AUTHORITY+W_RELEVANCE:.2f})")
    print(f"HALF_LIFE = {HALF_LIFE_HOURS:g}h. "
          f"decay(age) = 0.5**(age/{HALF_LIFE_HOURS:g}).\n")

    print("  Decay curve sample (recency multiplier vs article age):")
    for age in (0, 3, 6, 12, 24):
        mark = "   <- half-life (0.5)" if age == HALF_LIFE_HOURS else ""
        print(f"    age={age:>2}h  decay={recency(age):.4f}{mark}")
    print(f"\n  Source authority table:")
    for s, a in SOURCES.items():
        print(f"    {s:10s} authority={a:.2f}")
    print()

    reader = "tech enthusiast"
    interests = INTERESTS_TECH
    print(f"  Reader: {reader}  (interests: ai, openai, llm heavy; fed/rates low)\n")
    print("  Per-article signal breakdown:")
    print("    art  source     auth  age   recency  relevance   score")
    print("    " + "-" * 60)
    scored = []
    for art in CANDIDATES:
        rec, auth, rel, sc = rank_score(art, interests)
        scored.append((art, rec, auth, rel, sc))
        print(f"    {art.id}   {art.source:10s} {auth:.2f}  {art.age_hours:>4.1f}h  "
              f"{rec:.4f}   {rel:.4f}     {sc:.4f}")

    ranked = sorted(scored, key=lambda x: x[4], reverse=True)
    ranked_ids = [a.id for a, _, _, _, _ in ranked]
    print(f"\n  Ranked order (score desc): {', '.join(ranked_ids)}")
    print("  >>> a4 (fresh blog, 0.5h) beats a3 (Reuters fed story, 5h) for the")
    print("      tech reader: recency + relevance overcome a4's low authority.")
    print("  >>> a6 (Wired, openai+chips) ranks #3: relevant topics + decent age.")

    # =====================================================================
    # SECTION D: ADAPTIVE CRAWL SCHEDULING (poll interval optimization)
    # =====================================================================
    banner("Section D - Adaptive crawl scheduling (poll interval optimization)")
    print("Poll each feed at an interval INVERSELY proportional to its update")
    print("rate, with min/max clamps. Poll ~2x the update rate to stay fresh.\n")
    print(f"  raw_interval = (1440 / updates_per_day) * {SAFETY},  "
          f"clamped to [{MIN_INTERVAL:.0f}, {MAX_INTERVAL:.0f}] min\n")

    feed_rates = [
        ("wire (Reuters)",  48.0),
        ("tech (Wired)",     6.0),
        ("blog (personal)",  1.0),
    ]
    print(f"  {'feed':18s} {'updates/day':>11s} {'interval':>9s} {'polls/day':>10s} "
          f"{'% 304':>6s}")
    print("  " + "-" * 58)
    sched_rows = []
    for name, rate in feed_rates:
        interval = target_interval(rate)
        polls = polls_per_day(interval)
        modified = rate            # each update shows up in ~1 poll as "changed"
        pct_304 = (1 - modified / polls) * 100
        sched_rows.append((name, rate, interval, polls, modified, pct_304))
        print(f"  {name:18s} {rate:>11.0f} {interval:>8.0f}m {polls:>10.0f} "
              f"{pct_304:>5.0f}%")

    naive_polls = len(feed_rates) * (MINUTES_PER_DAY / MIN_INTERVAL)
    adaptive_polls = sum(r[3] for r in sched_rows)
    print(f"\n  Naive 'poll all every {MIN_INTERVAL:.0f} min'     : "
          f"{naive_polls:.0f} polls/day")
    print(f"  Adaptive (by update rate)         : {adaptive_polls:.0f} polls/day")
    print(f"  Reduction                         : "
          f"{(1-adaptive_polls/naive_polls)*100:.0f}%")

    FEED_KB = 250.0
    NM_KB = 0.5
    bw_naive = naive_polls * FEED_KB
    bw_cond = sum(r[4] * FEED_KB + (r[3] - r[4]) * NM_KB for r in sched_rows)
    print(f"\n  Bandwidth (3 feeds, {FEED_KB:.0f} KB full / {NM_KB} KB 304):")
    print(f"    naive full-fetch         = {bw_naive/1000:.1f} MB/day")
    print(f"    adaptive + conditional   = {bw_cond/1000:.1f} MB/day  "
          f"(saved {(1-bw_cond/bw_naive)*100:.0f}%)")

    print("\n  Adaptive convergence (exponential rush-in / back-off):")
    print("    rule: new content -> interval/=2 (min 15); none -> interval*=2 (max 1440)")
    print("    trace A: fast wire (always new) from 60m:")
    iv = 60.0
    trace_a = []
    for _ in range(5):
        iv = max(MIN_INTERVAL, iv / 2)        # always new -> rush in
        trace_a.append(iv)
    print(f"      {', '.join(f'{x:.0f}m' for x in trace_a)}  -> converges to {MIN_INTERVAL:.0f}m")
    print("    trace B: dead blog (never new) from 60m:")
    iv = 60.0
    trace_b = []
    for _ in range(5):
        iv = min(MAX_INTERVAL, iv * 2)        # never new -> back off
        trace_b.append(iv)
    print(f"      {', '.join(f'{x:.0f}m' for x in trace_b)}  -> converges to {MAX_INTERVAL:.0f}m")
    print("\n  >>> Adaptive scheduling makes polling proportional to how much a")
    print("      feed actually changes - fresh where it matters, quiet elsewhere.")

    # =====================================================================
    # SECTION E: PERSONALISED FEED GENERATION
    # =====================================================================
    banner("Section E - Personalised feed generation (same pool, two readers)")
    print("Merge candidates, dedup (already done), score against the reader's")
    print("interest profile, sort desc, return top-K. Same pool ranks differently")
    print("per reader because the RELEVANCE term differs.\n")

    def top_k(interests, k=3):
        out = []
        for art in CANDIDATES:
            _, _, _, sc = rank_score(art, interests)
            out.append((art.id, sc))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:k]

    tech_top = top_k(INTERESTS_TECH)
    fin_top = top_k(INTERESTS_FINANCE)
    print(f"  Reader A = tech enthusiast  (ai, openai, llm heavy)")
    print(f"    top-3: {', '.join(f'{i}({s:.3f})' for i, s in tech_top)}")
    print(f"  Reader B = finance analyst  (fed, rates, economy heavy)")
    print(f"    top-3: {', '.join(f'{i}({s:.3f})' for i, s in fin_top)}")
    print()
    print("  >>> Identical candidate pool, different top-3: a3/a5 (fed stories)")
    print("      surface for the finance reader but sink for the tech reader.")
    print("      Personalization is a READ-TIME re-scoring of the shared index.")

    # =====================================================================
    # SECTION F: SCALE ESTIMATION
    # =====================================================================
    banner("Section F - Scale estimation (Google News class)")
    sources = 100_000
    articles_per_source_day = 50
    articles_day = sources * articles_per_source_day
    avg_kb = 50
    storage_day_gb = articles_day * avg_kb / (1024 * 1024)   # KB -> GB
    storage_year_tb = storage_day_gb * 365 / 1024
    simhash_bytes = 8
    dedup_day_mb = articles_day * simhash_bytes / (1024 * 1024)        # bytes -> MB
    dedup_year_gb = dedup_day_mb * 365 / 1024                          # MB -> GB
    ingest_gbps = articles_day * avg_kb * 1024 * 8 / 1e9 / 86400
    avg_interval_min = 120.0
    polls_day = sources * (MINUTES_PER_DAY / avg_interval_min)
    pct_304_global = 0.60
    poll_bw_day_gb = polls_day * (FEED_KB * (1 - pct_304_global) + NM_KB * pct_304_global) / (1024 * 1024)

    print(f"  RSS / Atom sources             : {sources:,}")
    print(f"  Avg new articles/source/day    : {articles_per_source_day}")
    print(f"  Articles ingested/day          : {articles_day:,}")
    print(f"  Avg article size               : {avg_kb} KB")
    print(f"  Article storage/day            : {storage_day_gb:,.0f} GB")
    print(f"  Article storage/year           : {storage_year_tb:,.1f} TB")
    print()
    print(f"  Dedup index (SimHash, {simhash_bytes} B/article):")
    print(f"    per day                      : {dedup_day_mb:,.1f} MB")
    print(f"    per year                     : {dedup_year_gb:,.1f} GB  (tiny)")
    print()
    print(f"  Ingest bandwidth (bodies, avg) : {ingest_gbps:,.2f} Gbps avg  (~{ingest_gbps*5:,.2f} peak)")
    print(f"  Polling (avg interval {avg_interval_min:.0f}m, {pct_304_global*100:.0f}% 304):")
    print(f"    polls/day                    : {polls_day:,.0f}")
    print(f"    poll bandwidth/day           : {poll_bw_day_gb:,.0f} GB")
    print()
    print("  >>> The article store (~85 TB/yr) dominates; the SimHash dedup index")
    print("      is negligible (~14 GB/yr). Polling bandwidth is bounded by")
    print("      adaptive scheduling + conditional GET.")

    # =====================================================================
    # SECTION G: [check] ASSERTIONS
    # =====================================================================
    banner("Section G - [check] assertions")

    # 1. URL canonicalization collapses 4 mirror variants to 1.
    assert len(canon_set) == 1, f"4 mirror variants -> 1 canonical, got {len(canon_set)}"
    print(f"[check] canonicalization: 4 variants -> {len(canon_set)} canonical URL ... OK")

    # 2. FNV-1a determinism: same string -> same hash.
    assert fnv1a_64("hello") == fnv1a_64("hello")
    assert fnv1a_64("hello") != fnv1a_64("world")
    print(f"[check] fnv1a: deterministic, distinct for distinct input ... OK")

    # 3. SimHash self-distance is 0.
    assert d_self == 0, f"hamming(x,x) must be 0, got {d_self}"
    print(f"[check] simhash: hamming(exact, exact_copy) = {d_self} ... OK")

    # 4. Near-rewrite is detected as duplicate (small hamming <= threshold).
    assert d_near <= DUP_THRESHOLD, \
        f"near-rewrite hamming {d_near} must be <= {DUP_THRESHOLD}"
    assert is_near_duplicate(body_exact, body_near)
    print(f"[check] simhash: near-rewrite hamming={d_near} <= {DUP_THRESHOLD} "
          f"=> duplicate ... OK")

    # 5. Different story is NOT a duplicate (large hamming).
    assert d_diff >= 20, f"different story hamming {d_diff} must be >= 20"
    assert not is_near_duplicate(body_exact, body_diff)
    print(f"[check] simhash: different_story hamming={d_diff} >= 20 "
          f"=> not duplicate ... OK")

    # 6. LSH banding: near-dup shares >=1 band; different shares fewer.
    assert shared_near >= 1, "near-dup must share >=1 LSH band"
    print(f"[check] LSH: near_rewrite shares {shared_near}/{bands} bands "
          f"(>=1 candidate) ... OK")

    # 7. Ranking order for the tech reader matches the computed ranking.
    expected_order = ["a1", "a2", "a6", "a4", "a3", "a5"]
    assert ranked_ids == expected_order, \
        f"tech ranking {ranked_ids} != expected {expected_order}"
    print(f"[check] ranking: tech order = {','.join(ranked_ids)} ... OK")

    # 8. Recency decay: decay(6h) == 0.5 (half-life).
    assert abs(recency(6.0) - 0.5) < 1e-12
    print(f"[check] decay: decay(6h) = {recency(6.0)} == 0.5 (half-life) ... OK")

    # 9. Adaptive interval: daily blog -> 720 min, 2 polls/day.
    blog_interval = target_interval(1.0)
    assert blog_interval == 720.0, f"daily blog interval must be 720, got {blog_interval}"
    assert polls_per_day(blog_interval) == 2.0
    print(f"[check] scheduling: daily blog interval={blog_interval:.0f}m, "
          f"polls/day={polls_per_day(blog_interval):.0f} ... OK")

    # 10. Wire (48/day) clamps to MIN_INTERVAL=15.
    wire_interval = target_interval(48.0)
    assert wire_interval == MIN_INTERVAL, f"wire interval must be {MIN_INTERVAL}, got {wire_interval}"
    print(f"[check] scheduling: wire (48/day) interval={wire_interval:.0f}m "
          f"(MIN clamp) ... OK")

    # 11. Personalization: tech top1 = a1, finance top1 = a3.
    assert tech_top[0][0] == "a1", f"tech top1 must be a1, got {tech_top[0][0]}"
    assert fin_top[0][0] == "a3", f"finance top1 must be a3, got {fin_top[0][0]}"
    print(f"[check] personalization: tech top1={tech_top[0][0]}, "
          f"finance top1={fin_top[0][0]} ... OK")

    # 12. Scale: ~5M articles/day, ~85 TB/year.
    assert articles_day == 5_000_000
    assert abs(storage_year_tb - 85.0) < 1.0
    print(f"[check] scale: {articles_day:,} articles/day, "
          f"~{storage_year_tb:.1f} TB/year ... OK")

    # 13. Conditional GET bandwidth saves >= 80% vs naive full-fetch.
    bw_saving_pct = (1 - bw_cond / bw_naive) * 100
    assert bw_saving_pct >= 80.0, f"bandwidth saving {bw_saving_pct:.0f}% must be >= 80"
    print(f"[check] scheduling: conditional GET saves {bw_saving_pct:.0f}% "
          f"bandwidth vs naive ... OK")

    print()
    print("All [check] assertions passed. Re-run reproduces every number above.")


if __name__ == "__main__":
    main()
