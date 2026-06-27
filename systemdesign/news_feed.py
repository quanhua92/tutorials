"""
news_feed.py - Reference simulation of a News Feed system (Facebook / Twitter
style): the three fan-out strategies (fan-out-on-write / push, fan-out-on-read
/ pull, hybrid), the celebrity problem, EdgeRank-style feed ranking (affinity
x weight x decay), ranked timeline generation, and scale estimation.

This is the single source of truth that NEWS_FEED.md is built from. Every
operation count, ranking score, and scale number in the guide is printed by
this file. Deterministic (no randomness, no wall-clock). Re-run and re-paste
the output into the guide.

Run:
    python3 news_feed.py

========================================================================
THE INTUITION (read this first) - the newspaper delivery problem
========================================================================
A news feed is a personalised newspaper. The hard question is not "what is in
it" (posts from people you follow) but WHEN the work of assembling it happens:

  * FAN-OUT-ON-WRITE (push): the moment an author posts, the system runs
    around and drops a copy into EVERY follower's pre-built feed box.
    Reading is instant (just open your box). Writing is cheap for a normal
    user (500 copies) and catastrophic for a celebrity (1,000,000 copies).
    (Used by Twitter's early timeline.)
  * FAN-OUT-ON-READ (pull): the author drops ONE copy in a public slot.
    When you open your feed, the system runs around to ALL your followees'
    slots, gathers recent posts, merges, ranks. Writing is O(1); reading is
    O(number of followees) = 500 fetches per scroll.
    (Used by Facebook's news feed generation.)
  * HYBRID: push for normal authors (cheap, fast read), pull for celebrities
    (one write; followers pull the celebrity's recent posts at read time).
    Best of both, more machinery. (What real hyperscale systems converge to.)

Ranking is a SEPARATE axis. Once the candidate set exists (by push or pull),
a scorer decides ORDER. Facebook's EdgeRank was the classic formula:

    score = affinity(viewer, author) x weight(post) x decay(age)

  affinity : how close the viewer is to the author (interactions history).
  weight   : post-type + engagement value (video > photo > status).
  decay    : exponential time decay with a half-life (fresher = higher).

The NON-OBVIOUS parts this file drills into:
  1. The push/pull choice is a pure READ-COST vs WRITE-COST tradeoff, decided
     by the read:write ratio of the workload. Feeds are ~100:1 read-heavy, so
     push (pay once on write, read free) usually wins - UNTIL a celebrity
     shows up. (Sections A, B)
  2. ONE celebrity post under pure push = 1,000,000 feed-list writes. A
     thousand celebrities posting daily dominate the entire fan-out budget.
     (Section C)
  3. Hybrid keeps push's fast read for normal traffic and demotes only the
     celebrities to pull - the read path pays a small fixed tax (one extra
     fetch per celebrity you follow, ~5), not 1M writes per celebrity post.
     (Section D)
  4. EdgeRank is multiplicative: a celebrity video with 50k likes STILL ranks
     below a best friend's 2-hour-old photo, because personal affinity (0.9)
     crushes low affinity (0.2). Engagement volume is a signal, not a
     multiplier, in the basic formula. (Section E, F)
  5. Cursor-based (keyset) pagination, not OFFSET, because the feed is a
     moving target - new posts arriving mid-scroll make offset pagination
     return duplicates or skip items. (Section F)

========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
========================================================================
  fan-out          : spreading one piece of data to many recipients. The
                     fan-out FACTOR = number of followers = work multiplier.
  push (on-write)  : fan-out happens at publish time. Pre-computes feeds.
  pull (on-read)   : fan-out happens at read time. Computes feed on demand.
  celebrity        : a user whose follower count exceeds a threshold
                     (e.g. 1M). Their single post breaks pure push.
  affinity         : a [0,1] score of viewer-author closeness.
  weight           : a post-type / engagement multiplier (>=0).
  decay / half-life: time discount. decay(age) = 0.5 ** (age / half_life).
                     At age = half_life, the post is worth half as much.
  timeline         : the ranked list of posts returned for one feed fetch.
  cursor           : the last-returned post's id/timestamp used to fetch the
                     NEXT page deterministically (vs fragile OFFSET).
  write-op / read-op: abstract unit counted here (one feed-list append, one
                     followee fetch). The ratio is what matters.

========================================================================
THE ACTORS
========================================================================
  author           : the user creating a post.
  follower         : a user who subscribed to an author's posts.
  viewer           : the user requesting their feed (a follower).
  Post Service     : stores the canonical post (content + metadata).
  Social Graph     : the follow edges (who follows whom).
  Fan-out Service  : pushes post_ids to followers' feed boxes (push model).
  Feed / Timeline  : pre-built (push) or on-demand (pull) post_id list per
                     user, partitioned by user_id.
  Ranker           : scores the candidate post set and sorts.
  Feed Cache       : Redis, holds the hot working set of feed boxes / posts.
========================================================================
"""

from collections import defaultdict


# --------------------------------------------------------------------------
# Ranking primitives (EdgeRank-style). Pure functions, deterministic.
# --------------------------------------------------------------------------
HALF_LIFE_HOURS = 12.0   # a post is worth half its score every 12h

TYPE_WEIGHT = {
    "video": 2.0,
    "photo": 1.5,
    "link":  1.0,
    "status": 0.5,
}


class Post:
    """A single unit of feed content."""
    def __init__(self, post_id, author, ptype, age_hours, likes=0, comments=0):
        self.post_id = post_id
        self.author = author
        self.ptype = ptype
        self.age_hours = age_hours
        self.likes = likes
        self.comments = comments

    def __repr__(self):
        return (f"Post({self.post_id}, author={self.author}, "
                f"type={self.ptype}, age={self.age_hours}h)")


def decay(age_hours, half_life=HALF_LIFE_HOURS):
    """Exponential time decay. 1.0 at age=0, 0.5 at age=half_life."""
    return 0.5 ** (age_hours / half_life)


def affinity_score(viewer, author, affinity_map):
    """Look up viewer->author closeness in [0,1]. Default 0 (no edge)."""
    return affinity_map.get((viewer, author), 0.0)


def post_weight(post):
    """Type-based weight multiplier (video > photo > link > status)."""
    return TYPE_WEIGHT.get(post.ptype, 0.5)


def edge_rank(post, viewer, affinity_map):
    """EdgeRank score = affinity * weight * decay. Higher = ranks earlier."""
    aff = affinity_score(viewer, post.author, affinity_map)
    w = post_weight(post)
    d = decay(post.age_hours)
    return aff * w * d


# --------------------------------------------------------------------------
# SOCIAL GRAPH for the ranking example (Section E/F). Deterministic.
# --------------------------------------------------------------------------
RANK_VIEWER = "V"
RANK_AFFINITY = {
    ("V", "best_friend"): 0.9,   # close friend, many past interactions
    ("V", "casual"):      0.4,   # occasional interaction
    ("V", "rival"):       0.3,   # follow but rarely engage
    ("V", "celeb"):       0.2,   # follow a celebrity, low personal tie
}

# The candidate pool: 6 posts of mixed author/type/age, all from V's followees.
RANK_POOL = [
    Post("p1", "best_friend", "photo",  age_hours=2,  likes=50,   comments=10),
    Post("p2", "casual",      "video",  age_hours=6,  likes=5,    comments=2),
    Post("p3", "best_friend", "status", age_hours=20, likes=3,    comments=1),
    Post("p4", "celeb",       "video",  age_hours=1,  likes=50000,comments=2000),
    Post("p5", "rival",       "link",   age_hours=3,  likes=2,    comments=0),
    Post("p6", "best_friend", "video",  age_hours=30, likes=8,    comments=3),
]


# --------------------------------------------------------------------------
# Scenario constants (Sections A-D). One consistent social graph.
# --------------------------------------------------------------------------
VIEWER = "viewer_V"
NUM_FOLLOWEES = 500                 # V follows 500 authors
FOLLOWEES = ["f%03d" % i for i in range(NUM_FOLLOWEES)]
CELEBRITIES_FOLLOWED = ["celeb_1", "celeb_2", "celeb_3", "celeb_4", "celeb_5"]
NUM_NORMAL_FOLLOWERS = 500          # a normal author has ~500 followers
NUM_CELEB_FOLLOWERS = 1_000_000     # a celebrity has 1M followers
CELEB_THRESHOLD = 1_000_000         # >= this many followers => celebrity


def banner(title):
    line = "=" * 72
    print()
    print(line)
    print(" " + title)
    print(line)


# --------------------------------------------------------------------------
# FAN-OUT MODELS. Each counts write_ops and read_ops for the SAME scenario.
# --------------------------------------------------------------------------

def push_model_stats():
    """Fan-out-on-write. Publish pushes to every follower's feed box.
    write cost = number of followers; read cost = 1 (read your own box)."""
    # normal author publishes one post
    normal_writes = NUM_NORMAL_FOLLOWERS
    normal_reads = 1
    # celebrity publishes one post
    celeb_writes = NUM_CELEB_FOLLOWERS
    return {
        "normal_write": normal_writes, "normal_read": normal_reads,
        "celeb_write": celeb_writes, "celeb_read": 1,
    }


def pull_model_stats():
    """Fan-out-on-read. Publish stores once; read fetches from every followee.
    write cost = 1; read cost = number of followees you follow."""
    writes = 1   # one store per post
    reads = NUM_FOLLOWEES + len(CELEBRITIES_FOLLOWED)  # fetch each followee
    return {
        "write": writes, "read": reads,
        "celeb_write": 1, "celeb_read": reads,  # celebrity costs the SAME
    }


def hybrid_model_stats():
    """Push for normal authors, pull for celebrities.
    normal write = 500 (push); celebrity write = 1 (mark for pull).
    read = 1 (your pushed box) + 5 (pull each celebrity you follow)."""
    normal_writes = NUM_NORMAL_FOLLOWERS       # push to normal followers
    celeb_writes = 1                            # ONE write to a celeb list
    reads = 1 + len(CELEBRITIES_FOLLOWED)       # your box + 5 celeb pulls
    return {
        "normal_write": normal_writes, "celeb_write": celeb_writes,
        "read": reads,
    }


def main():
    banner("NEWS FEED - reference simulation (fan-out + ranking + scale)")
    print("Source of truth for NEWS_FEED.md and news_feed.html.")
    print("All numbers below are deterministic; re-run reproduces them.")

    # ---------------------------------------------------------------------
    # SECTION A: FAN-OUT-ON-WRITE (PUSH)
    # ---------------------------------------------------------------------
    banner("Section A - Fan-out-on-write (PUSH)")
    print("At publish time the post_id is APPENDED to every follower's feed")
    print("box. Reading your feed is just reading your box. The cost model:")
    print("  write cost  = number of followers (one feed-list append each)")
    print("  read  cost  = 1 (read your own feed box)\n")
    push = push_model_stats()
    print(f"  normal author posts ({NUM_NORMAL_FOLLOWERS} followers):")
    print(f"    write_ops = {push['normal_write']:,}    read_ops = {push['normal_read']}")
    print(f"  V reads feed (just opens own box):")
    print(f"    read_ops  = {push['normal_read']}")
    print()
    print("  >>> Push trades EXPENSIVE WRITES for FREE READS. Excellent when")
    print("      the workload is read-heavy (feeds are ~100:1 read:write).")
    print("  >>> The trap: what happens when the author has 1,000,000")
    print("      followers? See Section C.")

    # ---------------------------------------------------------------------
    # SECTION B: FAN-OUT-ON-READ (PULL)
    # ---------------------------------------------------------------------
    banner("Section B - Fan-out-on-read (PULL)")
    print("At publish time the post is stored ONCE in the author's slot.")
    print("At read time the system fetches recent posts from EVERY followee,")
    print("merges and ranks. The cost model:")
    print("  write cost  = 1 (store the post once)")
    print("  read  cost  = number of followees you follow (fetch each)\n")
    pull = pull_model_stats()
    print(f"  any author posts (store once):")
    print(f"    write_ops = {pull['write']}")
    print(f"  V reads feed (fetch from {NUM_FOLLOWEES} followees + "
          f"{len(CELEBRITIES_FOLLOWED)} celebrities):")
    print(f"    read_ops  = {pull['read']:,}   (={NUM_FOLLOWEES}+"
          f"{len(CELEBRITIES_FOLLOWED)})")
    print()
    print("  >>> Pull trades FREE WRITES for EXPENSIVE READS. A celebrity")
    print("      post costs the SAME to publish as a normal post (1 write).")
    print("  >>> The trap: every feed scroll fires "
          f"{pull['read']:,} fetches. Need a fan-in cache or the read path")
    print("      becomes a scatter-gather storm across the graph service.")

    # ---------------------------------------------------------------------
    # SECTION C: THE CELEBRITY PROBLEM
    # ---------------------------------------------------------------------
    banner("Section C - The celebrity problem (push breaks)")
    print(f"A celebrity has {NUM_CELEB_FOLLOWERS:,} followers. Under PUSH, one")
    print("celebrity post = one feed-list append PER follower:\n")
    print(f"  1 celebrity post -> {NUM_CELEB_FOLLOWERS:,} feed-list writes")
    print()
    # Scale it: N celebrities, M posts/day each
    NUM_CELEBS = 1000
    POSTS_PER_CELEB_PER_DAY = 5
    celeb_writes_per_day = (NUM_CELEBS * POSTS_PER_CELEB_PER_DAY *
                            NUM_CELEB_FOLLOWERS)
    print(f"  Extrapolate: {NUM_CELEBS:,} celebrities x "
          f"{POSTS_PER_CELEB_PER_DAY} posts/day each =")
    print(f"    {celeb_writes_per_day:,} feed-list writes/day from celebrities")
    print()
    # Compare to total normal-author writes/day
    TOTAL_POSTS_PER_DAY = 100_000_000
    AVG_NORMAL_FOLLOWERS = 500
    normal_writes_per_day = TOTAL_POSTS_PER_DAY * AVG_NORMAL_FOLLOWERS
    print(f"  vs normal authors: {TOTAL_POSTS_PER_DAY:,} posts/day x "
          f"{AVG_NORMAL_FOLLOWERS} avg followers =")
    print(f"    {normal_writes_per_day:,} feed-list writes/day from everyone")
    print()
    pct = celeb_writes_per_day / (celeb_writes_per_day + normal_writes_per_day) * 100
    print(f"  >>> {NUM_CELEBS:,} celebrities ({NUM_CELEBS/TOTAL_POSTS_PER_DAY*100:.4f}% of users) "
          f"generate {pct:.1f}% of ALL push writes. This is the celebrity")
    print("      hotspot: one viral account can saturate the fan-out queue and")
    print("      DELAY normal users' posts from reaching their feeds.")
    print("  >>> Fix: hybrid (Section D) - celebrities do NOT get pushed.")

    # ---------------------------------------------------------------------
    # SECTION D: HYBRID MODEL
    # ---------------------------------------------------------------------
    banner("Section D - Hybrid (push normal, pull celebrities)")
    print("Rule: if author's follower count >= CELEB_THRESHOLD, PULL (store")
    print("once, mark in a celebrity list). Otherwise PUSH (to all followers).")
    print(f"CELEB_THRESHOLD = {CELEB_THRESHOLD:,} followers.\n")
    hyb = hybrid_model_stats()
    print("  normal author posts (500 followers -> PUSH):")
    print(f"    write_ops = {hyb['normal_write']:,}  (pushed to each follower)")
    print(f"  celebrity posts (1M followers -> PULL):")
    print(f"    write_ops = {hyb['celeb_write']}  (one write to celeb list)")
    print(f"  V reads feed (own pushed box + pull each celebrity followed):")
    print(f"    read_ops  = {hyb['read']}   (= 1 box + {len(CELEBRITIES_FOLLOWED)} celeb pulls)")
    print()
    print("  Push writes saved per celebrity post:")
    saved = NUM_CELEB_FOLLOWERS - hyb["celeb_write"]
    print(f"    {NUM_CELEB_FOLLOWERS:,} - {hyb['celeb_write']} = {saved:,} writes AVOIDED")
    print()
    print("  >>> Read cost rises by a tiny constant (one fetch per celebrity")
    print(f"      you follow, ~{len(CELEBRITIES_FOLLOWED)}), while write cost for")
    print("      celebrities collapses from 1M to 1. The hybrid keeps push's")
    print("      fast read for the 99.99% normal case and pays a small read tax")
    print("      only for the celebrity tail.")

    # ---------------------------------------------------------------------
    # SECTION E: RANKING SIGNALS (EdgeRank decomposition)
    # ---------------------------------------------------------------------
    banner("Section E - Ranking signals (EdgeRank = affinity x weight x decay)")
    print(f"HALF_LIFE = {HALF_LIFE_HOURS:g}h. decay(age) = 0.5 ** (age/{HALF_LIFE_HOURS:g}).")
    print("Type weights: " + ", ".join(f"{k}={v}" for k, v in TYPE_WEIGHT.items()))
    print()
    print("  Decay curve sample (score multiplier vs post age):")
    for age in (0, 6, 12, 24, 48):
        print(f"    age={age:>2}h  decay={decay(age):.4f}"
              + ("   <- half-life (0.5)" if age == HALF_LIFE_HOURS else ""))
    print()
    print("  Affinity map for viewer V:")
    for (v, a), s in RANK_AFFINITY.items():
        print(f"    affinity({v}, {a}) = {s}")
    print()
    print("  Per-post signal breakdown for V's candidate pool:")
    print("    post  author        type   age   affinity weight  decay   score")
    print("    " + "-" * 66)
    breakdown = []
    for p in RANK_POOL:
        aff = affinity_score(RANK_VIEWER, p.author, RANK_AFFINITY)
        w = post_weight(p)
        d = decay(p.age_hours)
        s = aff * w * d
        breakdown.append((p, aff, w, d, s))
        print(f"    {p.post_id}   {p.author:12s} {p.ptype:6s} {p.age_hours:>3}h   "
              f"{aff:.2f}      {w:.1f}    {d:.4f}  {s:.4f}")
    print()
    print("  >>> Note p4 (celebrity video, 50,000 likes): its affinity is 0.2")
    print("      so even with weight=2.0 it scores LOWER than p1, your best")
    print("      friend's 2h-old photo. In basic EdgeRank, engagement VOLUME")
    print("      is not a multiplier - personal affinity dominates. (Real")
    print("      systems add popularity + ML features on top of this base.)")

    # ---------------------------------------------------------------------
    # SECTION F: RANKED TIMELINE GENERATION
    # ---------------------------------------------------------------------
    banner("Section F - Ranked timeline generation (top-K with cursor)")
    print("Generate V's feed: take candidate pool, score each, sort desc,")
    print("return top-K. Pagination uses a CURSOR (last post's id+score),")
    print("never OFFSET - the feed is a moving target (new posts arrive).")
    print()
    ranked = sorted(breakdown, key=lambda x: x[4], reverse=True)
    K = 4
    print(f"  Chronological order (by age asc):")
    chrono = ", ".join(p.post_id for p in sorted(RANK_POOL, key=lambda p: p.age_hours))
    print(f"    {chrono}")
    print(f"  Ranked order (by EdgeRank desc), top {K}:")
    ranked_ids = [p.post_id for p, _, _, _, _ in ranked]
    print(f"    full ranked: {', '.join(ranked_ids)}")
    for i, (p, aff, w, d, s) in enumerate(ranked[:K], 1):
        print(f"    #{i} {p.post_id}  {p.author:12s} {p.ptype:6s} "
              f"score={s:.4f}  (aff={aff:.2f} w={w:.1f} d={d:.4f})")
    print()
    print("  >>> Ranking REORDERS the feed: chronological p4(1h) drops to #3")
    print("      behind p1 and p2 because V's affinity to those authors is")
    print("      higher. Cursor = (p6, score=0.3182) resumes page 2 from")
    print("      there without OFFSET drift.")

    # ---------------------------------------------------------------------
    # SECTION G: SCALE ESTIMATION
    # ---------------------------------------------------------------------
    banner("Section G - Scale estimation (Facebook-class)")
    users = 1_000_000_000
    dau = 200_000_000
    posts_per_day = 100_000_000
    avg_followers = 500
    read_write_ratio = 100
    bytes_per_post = 1024
    days_per_year = 365
    print(f"  users (total)              : {users:,}")
    print(f"  DAU                        : {dau:,}")
    print(f"  new posts/day              : {posts_per_day:,}")
    print(f"  avg followers per post     : {avg_followers} (fan-out factor)")
    print(f"  read : write ratio         : {read_write_ratio}:1")
    print()
    push_writes_per_day = posts_per_day * avg_followers
    push_writes_per_sec = push_writes_per_day / 86400
    print(f"  PUSH feed-list writes/day  : {push_writes_per_day:,}")
    print(f"  PUSH writes/sec (avg)      : {push_writes_per_sec:,.0f}")
    feed_reads_per_day = posts_per_day * read_write_ratio
    feed_reads_per_sec = feed_reads_per_day / 86400
    print(f"  feed fetches/day (~{read_write_ratio}x writes) : {feed_reads_per_day:,}")
    print(f"  feed fetches/sec (avg)     : {feed_reads_per_sec:,.0f}")
    print()
    storage_posts_year_tb = posts_per_day * bytes_per_post * days_per_year / (1024**4)
    print(f"  post storage/year (~1KB)   : {storage_posts_year_tb:,.1f} TB")
    feed_entry_bytes = 16
    feed_storage_hot_gb = push_writes_per_day * 7 * feed_entry_bytes / (1024**3)
    print(f"  feed-list hot set (7-day TTL, {feed_entry_bytes}B/entry): "
          f"{feed_storage_hot_gb:,.0f} GB in Redis")
    print()
    print("  Celebrity hotspot (hybrid removes this from push):")
    hot_celebs = 1000
    celeb_followers = 2_000_000
    celeb_posts_day = 5
    celeb_writes_day = hot_celebs * celeb_posts_day * celeb_followers
    print(f"    {hot_celebs:,} celebrities x {celeb_posts_day}/day x "
          f"{celeb_followers:,} followers = {celeb_writes_day:,} writes/day")
    print(f"    that is {celeb_writes_day/push_writes_per_day*100:.1f}% of ALL push writes")

    # ---------------------------------------------------------------------
    # SECTION H: [check] ASSERTIONS
    # ---------------------------------------------------------------------
    banner("Section H - [check] assertions")

    # Check 1: decay at half-life is exactly 0.5.
    d_half = decay(HALF_LIFE_HOURS)
    assert abs(d_half - 0.5) < 1e-12, f"decay(half_life) must be 0.5, got {d_half}"
    print(f"[check] decay: decay(12h) = {d_half} == 0.5 (half-life) ... OK")

    # Check 2: decay at 2x half-life is exactly 0.25.
    d_double = decay(2 * HALF_LIFE_HOURS)
    assert abs(d_double - 0.25) < 1e-12, f"decay(2*half_life) must be 0.25, got {d_double}"
    print(f"[check] decay: decay(24h) = {d_double} == 0.25 ... OK")

    # Check 3: decay at 0 is exactly 1.0.
    d_zero = decay(0.0)
    assert d_zero == 1.0, f"decay(0) must be 1.0, got {d_zero}"
    print(f"[check] decay: decay(0h) = {d_zero} == 1.0 ... OK")

    # Check 4: push model - normal write = followers, read = 1.
    assert push["normal_write"] == NUM_NORMAL_FOLLOWERS
    assert push["normal_read"] == 1
    assert push["celeb_write"] == NUM_CELEB_FOLLOWERS
    print(f"[check] push: normal write={push['normal_write']}, "
          f"celeb write={push['celeb_write']:,}, read=1 ... OK")

    # Check 5: pull model - write = 1, read = followees + celebs.
    assert pull["write"] == 1
    assert pull["read"] == NUM_FOLLOWEES + len(CELEBRITIES_FOLLOWED)
    print(f"[check] pull: write=1, read={pull['read']} ... OK")

    # Check 6: celebrity push cost = 1,000,000 writes for one post.
    assert push["celeb_write"] == 1_000_000
    print(f"[check] celebrity: one celeb post = {push['celeb_write']:,} "
          f"push writes ... OK")

    # Check 7: hybrid - celeb write = 1, read = 1 + celebs followed.
    assert hyb["celeb_write"] == 1
    assert hyb["read"] == 1 + len(CELEBRITIES_FOLLOWED)
    print(f"[check] hybrid: celeb write=1, read={hyb['read']} "
          f"(1 box + {len(CELEBRITIES_FOLLOWED)} pulls) ... OK")

    # Check 8: hybrid saves 999,999 writes per celebrity post.
    assert saved == NUM_CELEB_FOLLOWERS - 1
    print(f"[check] hybrid: saves {saved:,} writes per celeb post ... OK")

    # Check 9: EdgeRank ranking order matches expected.
    expected_order = ["p1", "p2", "p4", "p6", "p5", "p3"]
    assert ranked_ids == expected_order, \
        f"ranking order mismatch: got {ranked_ids}, expected {expected_order}"
    print(f"[check] ranking: order = {','.join(ranked_ids)} ... OK")

    # Check 10: best friend's photo (p1) beats celebrity video (p4).
    score_p1 = edge_rank(RANK_POOL[0], RANK_VIEWER, RANK_AFFINITY)
    score_p4 = edge_rank(RANK_POOL[3], RANK_VIEWER, RANK_AFFINITY)
    assert score_p1 > score_p4, "p1 (aff=0.9) must beat p4 (aff=0.2)"
    print(f"[check] affinity: p1 score {score_p1:.4f} > p4 score {score_p4:.4f} "
          f"(friends beat celebrities) ... OK")

    # Check 11: scale math.
    assert push_writes_per_day == 50_000_000_000
    assert abs(storage_posts_year_tb - 33.6) < 0.5
    print(f"[check] scale: push writes/day = {push_writes_per_day:,}, "
          f"storage/year ~ {storage_posts_year_tb:.1f} TB ... OK")

    # Check 12: cursor vs offset reasoning - top-K is a stable prefix.
    assert ranked_ids[:K] == ["p1", "p2", "p4", "p6"]
    print(f"[check] cursor: top-{K} = {','.join(ranked_ids[:K])} ... OK")

    print()
    print("All [check] assertions passed. Re-run reproduces every number above.")


if __name__ == "__main__":
    main()
