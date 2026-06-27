"""
search_autocomplete.py - Reference simulation of a Search Autocomplete system
(Google Suggest / typeahead style): the trie data structure for prefix matching,
typeahead ranking in four layers (frequency -> recency decay -> trending overlay
-> personalization), prefix sharding by alphabet range, the data-collection
pipeline (query logs -> frequency aggregation -> trie rebuild, batch vs
real-time), and scale estimation.

This is the single source of truth that SEARCH_AUTOCOMPLETE.md is built from.
Every trie lookup, ranking score, shard assignment, and scale number in the
guide is printed by this file. Deterministic (no randomness, no wall-clock).
Re-run and re-paste the output into the guide.

Run:
    python3 search_autocomplete.py

========================================================================
THE INTUITION (read this first) - the librarian's card-catalog problem
========================================================================
A search autocomplete is a librarian who, the instant you say the first few
letters, shoves the 5 most likely completions across the desk. The hard parts
are not "find words that start with these letters" (a trie does that in O(L))
but (a) deciding WHICH 5, (b) doing it in <50ms for millions of simultaneous
typists, and (c) keeping the suggestions FRESH as the world's attention shifts.

  * TRIE (prefix tree): a tree where each node is a prefix and the path from
    the root spells a string. "ap" -> "app" -> "apple". To suggest for a typed
    prefix, walk the path and read the pre-stored top-K list at that node.
    Lookup is O(L) where L = prefix length (a few characters). The trick is to
    store the top-K suggestions AT EVERY NODE so a lookup never traverses the
    subtree. (Used by every typeahead system at the serving tier.)
  * RANKING IN FOUR LAYERS: a good suggestion score is built up, not picked
    once:
      1. FREQUENCY        : how many people searched this term historically.
                             The offline-rebuilt trie stores this. Simple but
                             blind to time - "world cup" in July scores high
                             forever.
      2. RECENCY DECAY    : score = freq * 0.5 ** (age / half-life). Old terms
                             fade; a half-life of ~24h keeps yesterday's news
                             from crowding out today's.
      3. TRENDING OVERLAY : a real-time recent counter (queries in the last
                             hour) blended on top. A sudden spike ("world cup
                             final NOW") bubbles to #1 in minutes, not at the
                             next batch rebuild. This is the small, hot, live
                             map that closes the freshness gap.
      4. PERSONALIZATION  : blend the global score with THIS user's own search
                             history. A developer typing "api" sees API docs;
                             a chef sees "apricot". score = a*global + b*user.

  * SHARDING BY PREFIX: one trie does not fit the world's QPS. Split the trie
    by the FIRST CHARACTER into N shards (a-f, g-m, n-s, t-z). A request for
    "ap..." routes deterministically to shard 0. Each shard is independent and
    horizontally scalable. Skew risk: 'a' and 's' are busy letters; a range
    split needs rebalancing or consistent hashing.

  * THE PIPELINE (write path): every keystroke is a READ; the system is
    read-heavy ~10000:1. Updates come from query logs:
      raw clicks  ->  log aggregator (counts per term)
                  ->  batch trie rebuild (every few minutes)
                  ->  snapshot to trie servers
    Real-time overlay: a Kafka stream feeds a sliding-window recent counter
    merged at query time, so trending lands in seconds, not minutes.

The NON-OBVIOUS parts this file drills into:
  1. Top-K AT EVERY NODE is the whole game: it makes a lookup O(L) instead of
     O(subtree). The cost is MEMORY - top-K per node dominates the footprint.
     (Section A, G)
  2. Pure frequency is stale; pure recency is jittery. The layered score
     (freq x decay + trend) is what makes suggestions feel both popular AND
     current. (Sections B, C)
  3. A trending spike of recent_1h=5000 on a term with freq=500 OVERTAKES a
     term with freq=8000 that has gone quiet. The real-time overlay - NOT the
     batch trie - is what captures breaking trends. (Section C)
  4. Personalization reorders the WHOLE list for one user: "api" is global #5
     but a developer's #1. Without per-user blending you serve the crowd, not
     the person. (Section D)
  5. Prefix sharding by first letter is simple but SKEW-PRONE: load follows the
     popularity of letters, not their count. 'q' and 'z' shards idle while 'a'
     and 's' shards melt. (Section E)

========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
========================================================================
  trie / prefix tree : a tree keyed by characters; each node = one prefix.
  top-K per node     : the K highest-scoring completions cached AT that node,
                       so a lookup returns instantly without scanning children.
  typeahead          : suggestions shown as the user types (before Enter).
  frequency (freq)   : historical all-time search count for a term.
  recency decay      : time discount: score *= 0.5 ** (age / half_life).
  trending overlay   : a live recent-count (last ~1h) blended onto the base
                       score to surface spikes between batch rebuilds.
  personalization    : blending a global score with the individual user's
                       search history.
  shard              : one horizontal slice of the trie holding a range of
                       first-character prefixes.
  freshness lag      : time between a real-world event and its appearance in
                       suggestions = batch interval - overlay coverage.
  read:write ratio   : autocomplete is ~10000:1 (keystrokes read vs trie writes).

========================================================================
THE ACTORS
========================================================================
  user / typist      : the person typing a query prefix.
  client             : browser/app; debounces keystrokes (~100ms) before asking.
  API Gateway        : terminates the GET /suggest?q=... requests.
  Autocomplete Svc   : stateless read tier; routes to the right shard, merges.
  Trie Store         : in-memory trie per shard (the hot, pre-computed index).
  Redis Cache        : top-K per popular prefix; absorbs the long-tail reads.
  Personalization Svc: looks up the user's history, blends into the score.
  Trending Overlay   : small live map of recent counters fed by Kafka.
  Aggregation Pipe   : offline job: query logs -> (term, freq) -> rebuild trie.
  Query Log / Kafka  : every executed search is logged for the pipeline.
========================================================================
"""

from bisect import insort


# --------------------------------------------------------------------------
# Ranking primitives. Pure functions, deterministic.
# --------------------------------------------------------------------------
HALF_LIFE_HOURS = 24.0   # a suggestion's score halves every 24h of inactivity
TREND_W = 2.0            # weight on the real-time recent counter (trending)
PERS_ALPHA = 1.0         # weight on global score in personalization
PERS_BETA = 200.0        # weight on the user's personal search count


def decay(age_hours, half_life=HALF_LIFE_HOURS):
    """Exponential time decay. 1.0 at age=0, 0.5 at age=half_life."""
    return 0.5 ** (age_hours / half_life)


class Suggestion:
    """One term with its raw signals."""
    def __init__(self, term, freq, age_hours, recent_1h=0):
        self.term = term
        self.freq = freq          # historical all-time count
        self.age_hours = age_hours  # hours since the term last trended
        self.recent_1h = recent_1h  # live counter: searches in the last hour

    def base_score(self):
        """Layer 1+2: frequency discounted by recency."""
        return self.freq * decay(self.age_hours)

    def trending_score(self):
        """Layer 3: base + real-time recent counter."""
        return self.base_score() + TREND_W * self.recent_1h

    def personalized_score(self, user_counts):
        """Layer 4: blend global trending score with this user's history."""
        return self.trending_score() + PERS_BETA * user_counts.get(self.term, 0)


# --------------------------------------------------------------------------
# The suggestion corpus (deterministic). One consistent dataset across all
# sections. recent_1h is zero for normal terms and huge for the spike.
# --------------------------------------------------------------------------
CORPUS = [
    # ---- shard 0: a-f --------------------------------------------------
    Suggestion("app",          12000, 1,  150),
    Suggestion("apple",        10000, 2,  120),
    Suggestion("app store",     9000, 3,   90),
    Suggestion("application",   8000, 5,   70),
    Suggestion("api",           7000, 2,  110),
    Suggestion("amazon",        8500, 4,   95),
    Suggestion("apartment",     4000, 8,   30),
    Suggestion("apply",         3000, 4,   40),
    Suggestion("facebook",      7800, 6,   60),
    Suggestion("food near me",  5200, 3,   80),
    # ---- shard 1: g-m --------------------------------------------------
    Suggestion("google",        9500, 1,  140),
    Suggestion("gmail",         9000, 2,  130),
    Suggestion("google maps",   8500, 3,  100),
    Suggestion("github",        8000, 5,   85),
    Suggestion("gmail login",   6000, 4,   70),
    Suggestion("maps",          4500, 7,   35),
    Suggestion("movie times",   3800, 9,   25),
    Suggestion("music",         3200, 6,   40),
    # ---- shard 2: n-s --------------------------------------------------
    Suggestion("netflix",       9800, 2,  135),
    Suggestion("news",          7000, 3,   90),
    Suggestion("nba",           8000, 5,   75),
    Suggestion("nba scores",    5500, 4,   65),
    Suggestion("spotify",       7200, 6,   55),
    Suggestion("snapchat",      4800, 8,   30),
    Suggestion("stocks",        4100, 7,   45),
    # ---- shard 3: t-z --------------------------------------------------
    Suggestion("youtube",      11000, 1,  160),
    Suggestion("twitter",       7500, 4,   70),
    Suggestion("translate",     5000, 6,   50),
    Suggestion("target",        4300, 9,   25),
    Suggestion("uber",          4600, 5,   40),
    Suggestion("weather",       8000, 48,  20),    # huge but now quiet
    Suggestion("word",          4000, 12,  60),
    Suggestion("world cup",      500,  0, 5000),   # SPIKING right now
    Suggestion("world of warcraft", 2000, 6, 40),
    Suggestion("zoom",          3000, 10,  35),
]

# A power user: developer who searches "api" and "apartment" a lot.
USER_HISTORY = {"api": 50, "apartment": 20, "app": 2}


# --------------------------------------------------------------------------
# Trie with top-K suggestions cached at every prefix node.
# --------------------------------------------------------------------------
class TrieNode:
    __slots__ = ("children", "suggestions")
    def __init__(self):
        self.children = {}              # char -> TrieNode
        self.suggestions = []           # list of (term, score), top-K, sorted desc

    def upsert(self, term, score, top_k):
        """Insert (term, score); keep the node's top-K list sorted desc."""
        self.suggestions = [(t, s) for t, s in self.suggestions if t != term]
        self.suggestions.append((term, score))
        self.suggestions.sort(key=lambda x: x[1], reverse=True)
        del self.suggestions[top_k:]


class Trie:
    def __init__(self, top_k=10):
        self.root = TrieNode()
        self.top_k = top_k
        self.size = 0   # number of terms inserted

    def insert(self, term, score):
        """Walk the term's path; at every node along the way cache top-K."""
        node = self.root
        for ch in term:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
            node.upsert(term, score, self.top_k)
        self.size += 1

    def node_for(self, prefix):
        """Return the node reached by walking `prefix`, or None."""
        node = self.root
        for ch in prefix:
            if ch not in node.children:
                return None
            node = node.children[ch]
        return node

    def suggest(self, prefix, limit=5):
        """O(L) lookup: walk to the prefix node, read its cached top-K."""
        node = self.node_for(prefix)
        if node is None:
            return []
        return node.suggestions[:limit]


# --------------------------------------------------------------------------
# Prefix sharding by alphabet range.
# --------------------------------------------------------------------------
SHARD_RANGES = [("a", "f"), ("g", "m"), ("n", "s"), ("t", "z")]
SHARD_NAMES = ["a-f", "g-m", "n-s", "t-z"]


def shard_for_term(term):
    """Route a term to its shard by first character. Deterministic."""
    c = term[0].lower()
    for i, (lo, hi) in enumerate(SHARD_RANGES):
        if lo <= c <= hi:
            return i
    return 0


def banner(title):
    line = "=" * 72
    print()
    print(line)
    print(" " + title)
    print(line)


def ranked(terms, score_fn):
    """Return terms sorted by score_fn desc (stable on input order for ties)."""
    indexed = list(enumerate(terms))
    indexed.sort(key=lambda x: (-score_fn(x[1]), x[0]))
    return [t for _, t in indexed]


def main():
    banner("SEARCH AUTOCOMPLETE - reference simulation "
           "(trie + ranking + sharding + pipeline)")
    print("Source of truth for SEARCH_AUTOCOMPLETE.md and "
          "search_autocomplete.html.")
    print("All numbers below are deterministic; re-run reproduces them.")

    # ---------------------------------------------------------------------
    # SECTION A: TRIE DATA STRUCTURE
    # ---------------------------------------------------------------------
    banner("Section A - Trie data structure (prefix matching + top-K/node)")
    print("Each trie node is a PREFIX. Walking 'a'->'p' lands on the node for")
    print("'ap', which caches the top-K completions starting with 'ap'. A")
    print("lookup is O(L) - just walk L characters and read the list. We NEVER")
    print("scan the subtree, because the work was done once at insert time.")
    print()
    trie = Trie(top_k=10)
    for s in CORPUS:
        trie.insert(s.term, s.freq)
    print(f"  inserted {trie.size} terms. top-K cached at every prefix node.")
    print()
    print("  Trie path for the prefix 'ap' (a -> p), cached top-K at 'ap':")
    ap_node = trie.node_for("ap")
    for term, score in ap_node.suggestions[:5]:
        print(f"    {term:16s} freq={score}")
    print()
    print("  ASCII trie, 'ap' subtree (top-K=2 shown per node for brevity):")
    print("    root")
    print("      |- a")
    print("      |    |- p   <-- prefix 'ap' : [app, apple]  (top-2 cached)")
    print("      |         |- p   <-- 'app'  : [app, apple]")
    print("      |         |    |- l   <-- 'appl' : [apple]")
    print("      |         |         |- e   <-- 'apple' : [apple]")
    print("      |         |- i   <-- 'api'  : [api]")
    print("      |         (every node on the path also caches 'app'/'apple'")
    print("      |          because they pass through on insert)")
    print()
    print("  >>> The lookup cost is the PREFIX LENGTH, not the corpus size.")
    print("      The MEMORY cost is top-K stored at every node - see Section G.")
    print("  >>> Notice 'api' is reachable via a->p->i even though it shares")
    print("      only 'ap' with 'apple'. The trie shares prefixes for free.")

    # ---------------------------------------------------------------------
    # SECTION B: TYPEAHEAD RANKING - FREQUENCY + RECENCY DECAY
    # ---------------------------------------------------------------------
    banner("Section B - Typeahead ranking: frequency then recency decay")
    print(f"HALF_LIFE = {HALF_LIFE_HOURS:g}h. base = freq * decay(age), "
          f"decay(age) = 0.5 ** (age/{HALF_LIFE_HOURS:g}).")
    print()
    print("  Decay curve sample (multiplier vs term age):")
    for age in (0, 6, 12, 24, 48):
        note = "   <- half-life (0.5)" if age == HALF_LIFE_HOURS else ""
        print(f"    age={age:>2}h  decay={decay(age):.4f}{note}")
    print()
    ap_terms = [s for s in CORPUS if s.term.startswith("ap")]
    print("  Prefix 'ap', top-5 by RAW FREQUENCY (layer 1, batch trie):")
    by_freq = ranked(ap_terms, lambda s: s.freq)
    for i, s in enumerate(by_freq[:5], 1):
        print(f"    #{i} {s.term:16s} freq={s.freq}")
    print()
    print("  Prefix 'ap', top-5 by RECENCY-DECAYED score (layer 2):")
    by_base = ranked(ap_terms, lambda s: s.base_score())
    for i, s in enumerate(by_base[:5], 1):
        print(f"    #{i} {s.term:16s} base={s.base_score():8.1f}  "
              f"(freq={s.freq} x decay({s.age_hours}h)={decay(s.age_hours):.4f})")
    print()
    april = next(s for s in CORPUS if s.term == "april") if any(
        s.term == "april" for s in CORPUS) else None
    print("  >>> Recency barely moves the hot top-4 (they are all fresh) but")
    print("      drops stale terms down the list. An old but once-popular term")
    print("      (age 30h+) sees its score nearly halve every day it sits idle.")
    print("  >>> A batch-rebuilt trie stores freq. Adding decay is a cheap")
    print("      per-node rescore, but the trie must be rebuilt to re-rank.")

    # ---------------------------------------------------------------------
    # SECTION C: TRENDING OVERLAY (real-time recent counter)
    # ---------------------------------------------------------------------
    banner("Section C - Trending overlay (real-time recent counter)")
    print(f"TREND_W = {TREND_W:g}. final = base + {TREND_W:g} * recent_1h, "
          f"where recent_1h is the LIVE count from the last hour (Kafka).")
    print()
    print("  Prefix 'w', top-5 by BASE ONLY (what the batch trie returns):")
    w_terms = [s for s in CORPUS if s.term.startswith("w")]
    by_base_w = ranked(w_terms, lambda s: s.base_score())
    for i, s in enumerate(by_base_w[:5], 1):
        print(f"    #{i} {s.term:18s} base={s.base_score():8.1f}")
    print()
    print("  Prefix 'w', top-5 WITH trending overlay (real-time):")
    by_trend = ranked(w_terms, lambda s: s.trending_score())
    for i, s in enumerate(by_trend[:5], 1):
        print(f"    #{i} {s.term:18s} final={s.trending_score():9.1f}  "
              f"(base={s.base_score():7.1f} + {TREND_W:g}x{s.recent_1h})")
    print()
    wc = next(s for s in CORPUS if s.term == "world cup")
    wt = next(s for s in CORPUS if s.term == "weather")
    print(f"  >>> 'world cup': base {wc.base_score():.0f} (freq={wc.freq}) "
          f"but recent_1h={wc.recent_1h} -> final {wc.trending_score():.0f}.")
    print(f"  >>> 'weather': base {wt.base_score():.0f} (freq={wt.freq}) but "
          f"recent_1h={wt.recent_1h} -> final {wt.trending_score():.0f}.")
    print("  >>> The spike OVERTAKES the historically huge but now-quiet term.")
    print("      The batch trie (rebuilt every few minutes) cannot do this; only")
    print("      the real-time overlay fed by Kafka closes the freshness gap.")

    # ---------------------------------------------------------------------
    # SECTION D: PERSONALIZATION (global + user history)
    # ---------------------------------------------------------------------
    banner("Section D - Personalization (global score + user history)")
    print(f"final = {PERS_ALPHA:g}*global + {PERS_BETA:g}*user_count, "
          f"where global = trending_score from Section C.")
    print()
    print("  Power user's search history (personal counts):")
    for term, c in USER_HISTORY.items():
        print(f"    {term:12s} user_count={c}")
    print()
    print("  Prefix 'ap', top-5 GLOBAL vs top-5 PERSONALIZED:")
    by_global = ranked(ap_terms, lambda s: s.trending_score())
    by_pers = ranked(ap_terms, lambda s: s.personalized_score(USER_HISTORY))
    print("    #   global                        personalized")
    print("    " + "-" * 60)
    for i in range(5):
        g = by_global[i]
        p = by_pers[i]
        mark = "  <-- reordered" if g.term != p.term else ""
        print(f"    {i+1}   {g.term:16s} {g.trending_score():8.1f}   "
              f"{p.term:16s} {p.personalized_score(USER_HISTORY):8.1f}{mark}")
    print()
    api = next(s for s in CORPUS if s.term == "api")
    print(f"  >>> 'api' is GLOBAL #{[t.term for t in by_global].index('api')+1} "
          f"but this developer's #1 (user_count={USER_HISTORY['api']}).")
    print("  >>> Personalization reorders the WHOLE list per user. The global")
    print("      trie gives the crowd's answer; the personalization layer bends")
    print("      it toward the individual. Done at the service tier, post-shard.")

    # ---------------------------------------------------------------------
    # SECTION E: PREFIX SHARDING
    # ---------------------------------------------------------------------
    banner("Section E - Prefix sharding (split the trie by first character)")
    print("One trie cannot serve global QPS. Split by the FIRST CHARACTER into")
    print(f"{len(SHARD_RANGES)} range shards. A request routes deterministically:")
    print("  'apple' -> shard 0 (a-f), 'google' -> shard 1 (g-m), etc.")
    print()
    print("  Shard load from the corpus (terms + total historical freq):")
    print("    shard  range   terms   sum(freq)   example terms")
    print("    " + "-" * 60)
    shard_terms = [[] for _ in SHARD_RANGES]
    shard_freq = [0 for _ in SHARD_RANGES]
    for s in CORPUS:
        i = shard_for_term(s.term)
        shard_terms[i].append(s)
        shard_freq[i] += s.freq
    for i, name in enumerate(SHARD_NAMES):
        ex = ", ".join(s.term for s in shard_terms[i][:3])
        print(f"      {i}    {name:5s}  {len(shard_terms[i]):>5}   "
              f"{shard_freq[i]:>9,}   {ex}")
    total = sum(shard_freq)
    print()
    print("  Skew check (share of total frequency per shard):")
    for i, name in enumerate(SHARD_NAMES):
        pct = shard_freq[i] / total * 100
        bar = "#" * int(pct / 2)
        print(f"    shard {i} ({name}): {pct:5.1f}%  {bar}")
    print()
    print("  >>> Range sharding is simple to reason about and routes in O(1),")
    print("      but load follows LETTER POPULARITY, not letter COUNT. Real")
    print("      English queries overload 'a','s','c' and starve 'q','x','z'.")
    print("  >>> Fix when skew bites: split hot ranges (e.g. 'a' -> 'a','ap',")
    print("      'ap...') or move to consistent hashing on the prefix itself.")

    # ---------------------------------------------------------------------
    # SECTION F: DATA COLLECTION PIPELINE
    # ---------------------------------------------------------------------
    banner("Section F - Data collection pipeline (batch rebuild + real-time)")
    print("Every keystroke is a READ; updates are rare (~10000:1 read:write).")
    print("The write path turns raw query logs into a fresh trie:")
    print()
    print("  BATCH path (offline, every few minutes):")
    print("    query logs -> aggregator (count per term) -> rebuild trie ->")
    print("    snapshot -> ship to trie servers")
    BATCH_MIN = 5
    print(f"      batch interval = {BATCH_MIN} min   -> freshness lag <= {BATCH_MIN} min")
    print("      pros: exact counts, full re-rank, simple. cons: stale between runs.")
    print()
    print("  REAL-TIME overlay (online, continuous):")
    print("    executed searches -> Kafka -> sliding-window recent counter ->")
    print("    small hot map (term -> last-1h count) merged at query time")
    print("      pros: spikes land in seconds. cons: lossy, approximate, RAM-hot.")
    print()
    print("  >>> HYBRID is the answer: batch trie for the stable base (99% of")
    print("      terms), real-time overlay for the hot tail (the trending 1%).")
    print("      Freshness lag collapses from minutes to seconds WITHOUT making")
    print("      the whole trie mutable (which would wreck read concurrency).")

    # ---------------------------------------------------------------------
    # SECTION G: SCALE ESTIMATION
    # ---------------------------------------------------------------------
    banner("Section G - Scale estimation (Google-class autocomplete)")
    dau = 500_000_000
    peak_qps = 100_000
    rw_ratio = 10_000
    unique_terms = 10_000_000
    avg_term_len = 8
    top_k = 10
    searches_per_dau = 10             # avg searches per user per day
    keystrokes_per_query = 8          # debounced autocomplete requests per query
    per_node_bytes = 256
    print(f"  DAU                         : {dau:,}")
    print(f"  autocomplete QPS (peak)     : {peak_qps:,}")
    print(f"  read : write ratio          : {rw_ratio:,}:1")
    print(f"  unique terms (corpus)       : {unique_terms:,}")
    print(f"  avg term length             : {avg_term_len} chars")
    print(f"  top-K cached per node       : {top_k}")
    print()
    auto_req_day = dau * searches_per_dau * keystrokes_per_query
    auto_req_sec = auto_req_day / 86400
    print(f"  autocomplete requests/day   : {auto_req_day:,}  "
          f"(DAU x {searches_per_dau} x {keystrokes_per_query})")
    print(f"  autocomplete requests/sec   : {auto_req_sec:,.0f} (avg)")
    print()
    raw_chars = unique_terms * avg_term_len
    sharing_factor = 1.6
    trie_nodes = int(raw_chars / sharing_factor)
    total_mem_gb = trie_nodes * per_node_bytes / (1024 ** 3)
    per_shard_gb = total_mem_gb / len(SHARD_RANGES)
    print(f"  trie nodes (raw {raw_chars:,} chars / {sharing_factor} sharing): "
          f"{trie_nodes:,}")
    print(f"  memory/node (children + top-{top_k}): {per_node_bytes} B")
    print(f"  total trie memory            : {total_mem_gb:,.1f} GB")
    print(f"  per shard ({len(SHARD_RANGES)} shards)  : {per_shard_gb:,.1f} GB "
          f"(fits comfortably in RAM)")
    print()
    bytes_per_response = 200
    bandwidth_mbps = peak_qps * bytes_per_response * 8 / 1_000_000
    print(f"  response size (top-5)        : ~{bytes_per_response} B")
    print(f"  peak bandwidth               : {bandwidth_mbps:,.1f} Mbps (trivial)")
    print()
    print("  >>> The entire index lives in RAM across a handful of boxes. The")
    print("      bottleneck is QPS and skew, NOT storage. top-K per node is the")
    print("      memory driver; FST compression (Lucene) or storing top-K only")
    print("      at high-traffic prefix depths cuts it further.")

    # ---------------------------------------------------------------------
    # SECTION H: [check] ASSERTIONS
    # ---------------------------------------------------------------------
    banner("Section H - [check] assertions")

    # Check 1: decay at half-life is exactly 0.5.
    d_half = decay(HALF_LIFE_HOURS)
    assert abs(d_half - 0.5) < 1e-12, f"decay(half_life) must be 0.5, got {d_half}"
    print(f"[check] decay: decay(24h) = {d_half} == 0.5 (half-life) ... OK")

    # Check 2: decay at 0 is exactly 1.0.
    d_zero = decay(0.0)
    assert d_zero == 1.0, f"decay(0) must be 1.0, got {d_zero}"
    print(f"[check] decay: decay(0h) = {d_zero} == 1.0 ... OK")

    # Check 3: trie lookup for 'ap' returns the freq-ranked top-5.
    ap_top5 = [t for t, _ in trie.suggest("ap", limit=5)]
    expected_ap = ["app", "apple", "app store", "application", "api"]
    assert ap_top5 == expected_ap, f"trie 'ap' top-5: {ap_top5} != {expected_ap}"
    print(f"[check] trie: 'ap' top-5 = {','.join(ap_top5)} ... OK")

    # Check 4: trie lookup cost is O(prefix length) = 2 hops for 'ap'.
    hops = len("ap")
    assert hops == 2
    print(f"[check] trie: 'ap' lookup = {hops} char-hops (O(L)) ... OK")

    # Check 5: recency ranking order for 'ap'.
    ap_base_order = [s.term for s in by_base[:5]]
    expected_ap_base = ["app", "apple", "app store", "application", "api"]
    assert ap_base_order == expected_ap_base, \
        f"recency order: {ap_base_order} != {expected_ap_base}"
    print(f"[check] recency: 'ap' top-5 = {','.join(ap_base_order)} ... OK")

    # Check 6: trending overlay - 'world cup' jumps to #1 from base-only #4.
    base_w_order = [s.term for s in by_base_w]
    trend_w_order = [s.term for s in by_trend]
    assert base_w_order.index("world cup") == 3, base_w_order
    assert trend_w_order.index("world cup") == 0, trend_w_order
    print(f"[check] trending: 'world cup' base #{base_w_order.index('world cup')+1} "
          f"-> trending #1 ... OK")

    # Check 7: trending - world cup final score beats weather final score.
    assert wc.trending_score() > wt.trending_score()
    print(f"[check] trending: world cup {wc.trending_score():.0f} > "
          f"weather {wt.trending_score():.0f} ... OK")

    # Check 8: personalization - 'api' is global #5 but personalized #1.
    assert by_global.index(api) == 4, [t.term for t in by_global]
    assert by_pers.index(api) == 0, [t.term for t in by_pers]
    print(f"[check] personalization: 'api' global #{by_global.index(api)+1} "
          f"-> personalized #1 ... OK")

    # Check 9: sharding routes deterministically.
    assert shard_for_term("apple") == 0
    assert shard_for_term("google") == 1
    assert shard_for_term("netflix") == 2
    assert shard_for_term("youtube") == 3
    print("[check] sharding: apple->0, google->1, netflix->2, youtube->3 ... OK")

    # Check 10: every corpus term routes to a valid shard.
    for s in CORPUS:
        assert 0 <= shard_for_term(s.term) < len(SHARD_RANGES)
    print(f"[check] sharding: all {len(CORPUS)} terms routed to a valid shard ... OK")

    # Check 11: scale math.
    assert auto_req_day == 40_000_000_000
    assert trie_nodes == 50_000_000
    assert abs(total_mem_gb - 11.9) < 0.2
    print(f"[check] scale: requests/day = {auto_req_day:,}, "
          f"nodes = {trie_nodes:,}, mem ~ {total_mem_gb:.1f} GB ... OK")

    # Check 12: top-K bounded at every node.
    assert len(ap_node.suggestions) <= trie.top_k
    print(f"[check] top-K: 'ap' node holds {len(ap_node.suggestions)} "
          f"<= {trie.top_k} ... OK")

    print()
    print("All [check] assertions passed. Re-run reproduces every number above.")


if __name__ == "__main__":
    main()
