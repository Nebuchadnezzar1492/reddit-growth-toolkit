#!/usr/bin/env python3
"""Reddit growth toolkit — config-driven thread tracker, karma farmer, and comment performance analyzer."""

import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


CONFIG = None
SCORING = None
ACCOUNTS = None
SUBREDDITS = None
KARMA_FARMING_SUBS = None
KEYWORDS = None
PRODUCT_NAME = None
MENTION_KEYWORDS = None
FIND_SETTINGS = None
FETCH_SETTINGS = None
DB_PATH = None


def load_config():
    """Load config.json, fall back to config.example.json with warning."""
    config_path = SCRIPT_DIR / "config.json"
    example_path = SCRIPT_DIR / "config.example.json"

    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)

    if example_path.exists():
        print("WARNING: config.json not found, using config.example.json")
        print("  copy config.example.json to config.json and customize it\n")
        with open(example_path) as f:
            return json.load(f)

    print("ERROR: no config.json or config.example.json found")
    sys.exit(1)


def validate_config(config):
    """Validate required config keys exist. Exits with clear error if not."""
    required = {
        "accounts": list,
        "product": dict,
        "subreddits": dict,
        "keywords": list,
    }
    for key, expected_type in required.items():
        if key not in config:
            print(f"ERROR: config.json missing required key: '{key}'")
            sys.exit(1)
        if not isinstance(config[key], expected_type):
            print(f"ERROR: config.json '{key}' must be a {expected_type.__name__}")
            sys.exit(1)

    # nested required keys
    nested = {
        ("product", "name"): str,
        ("product", "mention_keywords"): list,
        ("subreddits", "niche"): list,
        ("subreddits", "karma_farming"): list,
    }
    for (parent, child), expected_type in nested.items():
        if child not in config[parent]:
            print(f"ERROR: config.json missing required key: '{parent}.{child}'")
            sys.exit(1)
        if not isinstance(config[parent][child], expected_type):
            print(f"ERROR: config.json '{parent}.{child}' must be a {expected_type.__name__}")
            sys.exit(1)

    if not config["accounts"]:
        print("ERROR: config.json 'accounts' cannot be empty")
        sys.exit(1)


def load_scoring():
    """Load scoring.json, fall back to scoring.default.json."""
    scoring_path = SCRIPT_DIR / "scoring.json"
    default_path = SCRIPT_DIR / "scoring.default.json"

    if scoring_path.exists():
        with open(scoring_path) as f:
            return json.load(f)

    if default_path.exists():
        with open(default_path) as f:
            return json.load(f)

    return {}


def setup_db_path():
    """Set up DB path in data/ dir, auto-migrate from old location."""
    data_dir = SCRIPT_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    new_path = data_dir / "tracker.db"

    # auto-migrate from old location
    old_path = SCRIPT_DIR / "reddit_tracker.db"
    if old_path.exists() and not new_path.exists():
        shutil.move(str(old_path), str(new_path))
        # also move WAL/SHM if present
        for ext in ["-wal", "-shm"]:
            old_extra = SCRIPT_DIR / f"reddit_tracker.db{ext}"
            if old_extra.exists():
                shutil.move(str(old_extra), str(data_dir / f"tracker.db{ext}"))
        print(f"migrated database to {new_path}")

    return new_path


def init():
    """Initialize config, scoring, and DB. Call once from main()."""
    global CONFIG, SCORING, ACCOUNTS, SUBREDDITS, KARMA_FARMING_SUBS
    global KEYWORDS, PRODUCT_NAME, MENTION_KEYWORDS, FIND_SETTINGS, FETCH_SETTINGS, DB_PATH

    CONFIG = load_config()
    validate_config(CONFIG)
    SCORING = load_scoring()

    # accounts can be list of strings or list of objects with "username" key
    raw_accounts = CONFIG["accounts"]
    if raw_accounts and isinstance(raw_accounts[0], dict):
        ACCOUNTS = [a["username"] for a in raw_accounts]
    else:
        ACCOUNTS = raw_accounts
    SUBREDDITS = CONFIG["subreddits"]["niche"]
    KARMA_FARMING_SUBS = CONFIG["subreddits"]["karma_farming"]
    KEYWORDS = CONFIG["keywords"]
    PRODUCT_NAME = CONFIG["product"]["name"]
    MENTION_KEYWORDS = CONFIG["product"]["mention_keywords"]
    FIND_SETTINGS = CONFIG.get("find_settings", {})
    FETCH_SETTINGS = CONFIG.get("fetch_settings", {})

    DB_PATH = setup_db_path()


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            subreddit TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            url TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            num_comments INTEGER DEFAULT 0,
            created_utc REAL,
            seen_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_url TEXT NOT NULL,
            comment_text TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            last_karma INTEGER DEFAULT 0,
            last_checked TEXT,
            mentioned_product INTEGER DEFAULT 0,
            subreddit TEXT,
            thread_score_at_reply INTEGER DEFAULT 0,
            thread_comments_at_reply INTEGER DEFAULT 0,
            thread_age_hours REAL DEFAULT 0,
            reply_position TEXT,
            day_of_week TEXT,
            hour_utc INTEGER DEFAULT 0
        )
    """)
    # migrate: add new columns if missing
    existing = [row[1] for row in db.execute("PRAGMA table_info(comments)").fetchall()]
    migrations = {
        "subreddit": "TEXT",
        "thread_score_at_reply": "INTEGER DEFAULT 0",
        "thread_comments_at_reply": "INTEGER DEFAULT 0",
        "thread_age_hours": "REAL DEFAULT 0",
        "reply_position": "TEXT",
        "day_of_week": "TEXT",
        "hour_utc": "INTEGER DEFAULT 0",
        "account": "TEXT",
        "reddit_comment_id": "TEXT",
        "thread_title": "TEXT",
        "context_enriched": "INTEGER DEFAULT 0",
    }
    for col, coltype in migrations.items():
        if col not in existing:
            db.execute(f"ALTER TABLE comments ADD COLUMN {col} {coltype}")
    # rename mentioned_olares -> mentioned_product
    if "mentioned_olares" in existing and "mentioned_product" not in existing:
        db.execute("ALTER TABLE comments RENAME COLUMN mentioned_olares TO mentioned_product")
    db.commit()
    return db


def curl_json(url):
    """Fetch JSON from a URL using curl (reddit blocks urllib)."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-H", f"User-Agent: {USER_AGENT}", url],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"  error fetching {url}: {e}")
        return None


def fetch_top_comments(thread_url, limit=5):
    """Fetch top-level comments from a thread. Returns list of (score, text) tuples."""
    # ensure www.reddit.com (required for JSON API)
    normalized = thread_url.replace("https://reddit.com", "https://www.reddit.com")
    url = normalized.rstrip("/") + ".json?sort=top&limit=50"
    data = curl_json(url)
    if not data or not isinstance(data, list) or len(data) < 2:
        return []
    comments = []
    for c in data[1].get("data", {}).get("children", []):
        if c.get("kind") != "t1":
            continue
        cd = c.get("data", {})
        body = (cd.get("body") or "").replace("\n", " ").strip()
        if not body:
            continue
        comments.append((cd.get("score", 0), body[:120]))
    comments.sort(key=lambda x: x[0], reverse=True)
    return comments[:limit]


def fetch_subreddit(sub):
    """Fetch new threads from a subreddit's JSON API."""
    limit = FETCH_SETTINGS.get("posts_per_sub", 50)
    url = f"https://www.reddit.com/r/{sub}/new.json?limit={limit}"
    data = curl_json(url)
    if data is None:
        return []
    return data.get("data", {}).get("children", [])


def matches_keywords(title, body):
    """Check if thread title or body contains any target keyword."""
    text = f"{title} {body or ''}".lower()
    return any(kw in text for kw in KEYWORDS)


def cmd_fetch():
    """Discover new threads from target subreddits."""
    db = get_db()
    total_new = 0

    for sub in SUBREDDITS:
        print(f"fetching r/{sub}...")
        posts = fetch_subreddit(sub)
        new_count = 0

        for post in posts:
            p = post.get("data", {})
            post_id = p.get("id", "")
            title = p.get("title", "")
            body = p.get("selftext", "")

            if not matches_keywords(title, body):
                continue

            existing = db.execute("SELECT id FROM threads WHERE id = ?", (post_id,)).fetchone()
            if existing:
                continue

            permalink = p.get("permalink", "")
            thread_url = f"https://www.reddit.com{permalink}" if permalink else ""

            db.execute(
                "INSERT INTO threads (id, subreddit, title, body, url, score, num_comments, created_utc, seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    post_id, sub, title, body, thread_url,
                    p.get("score", 0), p.get("num_comments", 0),
                    p.get("created_utc", 0),
                    datetime.utcnow().isoformat()
                )
            )
            new_count += 1

        db.commit()
        total_new += new_count
        print(f"  found {new_count} new matching threads")

        time.sleep(FETCH_SETTINGS.get("rate_limit_seconds", 2))

    print(f"\ntotal new threads: {total_new}")
    db.close()


def cmd_log(thread_url, comment_text):
    """Log a comment we posted to a thread, auto-fetching thread context."""
    db = get_db()
    now = datetime.utcnow()
    mentioned = 1 if any(kw in comment_text.lower() for kw in MENTION_KEYWORDS) else 0

    # fetch thread context
    subreddit = ""
    thread_score = 0
    thread_comments = 0
    thread_age_hours = 0
    reply_position = "unknown"

    json_url = thread_url.rstrip("/") + ".json"
    data = curl_json(json_url)
    if data and isinstance(data, list) and len(data) >= 1:
        post = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
        subreddit = post.get("subreddit", "")
        thread_score = post.get("score", 0)
        thread_comments = post.get("num_comments", 0)
        created = post.get("created_utc", 0)
        if created:
            thread_age_hours = (now.timestamp() - created) / 3600

        # estimate reply position
        if thread_comments < 10:
            reply_position = "early"
        elif thread_comments < 50:
            reply_position = "mid"
        elif thread_comments < 200:
            reply_position = "late"
        else:
            reply_position = "buried"

    db.execute(
        "INSERT INTO comments (thread_url, comment_text, posted_at, mentioned_product, "
        "subreddit, thread_score_at_reply, thread_comments_at_reply, thread_age_hours, "
        "reply_position, day_of_week, hour_utc, context_enriched) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            thread_url, comment_text, now.isoformat(), mentioned,
            subreddit, thread_score, thread_comments, round(thread_age_hours, 1),
            reply_position, now.strftime("%A"), now.hour
        )
    )
    db.commit()
    print(f"logged comment:")
    print(f"  subreddit: r/{subreddit}")
    print(f"  thread score: {thread_score} pts, {thread_comments} comments")
    print(f"  thread age: {thread_age_hours:.1f}h")
    print(f"  reply position: {reply_position}")
    print(f"  posted: {now.strftime('%A')} {now.hour}:00 UTC")
    print(f"  {PRODUCT_NAME} mentioned: {'yes' if mentioned else 'no'}")
    db.close()


def cmd_report():
    """Generate a performance report."""
    db = get_db()
    now = datetime.utcnow()
    day_ago = (now - timedelta(hours=24)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    # --- new threads last 24h ---
    threads = db.execute(
        "SELECT subreddit, title, url, score, num_comments, created_utc "
        "FROM threads WHERE seen_at > ? ORDER BY score DESC",
        (day_ago,)
    ).fetchall()

    print("=" * 60)
    print(f"REDDIT TRACKER REPORT - {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    print(f"\n## NEW THREADS (last 24h): {len(threads)}")
    print("-" * 40)
    if threads:
        for t in threads[:30]:
            age_hrs = (now.timestamp() - (t["created_utc"] or 0)) / 3600
            print(f"  [{t['score']:>4} pts | {t['num_comments']:>3} comments | {age_hrs:.0f}h ago] r/{t['subreddit']}")
            print(f"    {t['title'][:80]}")
            print(f"    {t['url']}")
            print()
    else:
        print("  no new threads found")

    # --- thread breakdown by sub ---
    print("\n## THREADS BY SUBREDDIT (last 24h)")
    print("-" * 40)
    for sub in SUBREDDITS:
        count = db.execute(
            "SELECT COUNT(*) as c FROM threads WHERE subreddit = ? AND seen_at > ?",
            (sub, day_ago)
        ).fetchone()["c"]
        print(f"  r/{sub}: {count}")

    # --- our comment performance ---
    comments = db.execute(
        "SELECT * FROM comments ORDER BY posted_at DESC"
    ).fetchall()

    print(f"\n## OUR COMMENTS: {len(comments)} total")
    print("-" * 40)

    if comments:
        total_karma = sum(c["last_karma"] for c in comments)
        product_comments = [c for c in comments if c["mentioned_product"]]
        organic_comments = [c for c in comments if not c["mentioned_product"]]

        print(f"  total karma earned: {total_karma}")
        print(f"  comments with {PRODUCT_NAME} mention: {len(product_comments)}")
        print(f"  karma-building comments: {len(organic_comments)}")

        if product_comments:
            avg_product = sum(c["last_karma"] for c in product_comments) / len(product_comments)
            print(f"  avg karma ({PRODUCT_NAME} mentions): {avg_product:.1f}")
        if organic_comments:
            avg_organic = sum(c["last_karma"] for c in organic_comments) / len(organic_comments)
            print(f"  avg karma (no mention): {avg_organic:.1f}")

        # recent comments
        recent = [c for c in comments if c["posted_at"] > week_ago]
        if recent:
            print(f"\n  recent comments (last 7 days):")
            for c in recent[:10]:
                preview = c["comment_text"][:70].replace("\n", " ")
                tag = f" [{PRODUCT_NAME.upper()}]" if c["mentioned_product"] else ""
                print(f"    [{c['last_karma']:>3} karma] {preview}...{tag}")
                print(f"      {c['thread_url']}")
                print()

        # best performers
        top = db.execute(
            "SELECT * FROM comments ORDER BY last_karma DESC LIMIT 5"
        ).fetchall()
        if top and any(c["last_karma"] > 0 for c in top):
            print(f"\n  top performing comments:")
            for c in top:
                if c["last_karma"] > 0:
                    preview = c["comment_text"][:70].replace("\n", " ")
                    print(f"    [{c['last_karma']:>3} karma] {preview}...")
    else:
        print("  no comments logged yet")

    # --- reply opportunities ---
    hot_threads = db.execute(
        "SELECT subreddit, title, url, score, num_comments FROM threads "
        "WHERE seen_at > ? AND score >= 3 ORDER BY score DESC LIMIT 10",
        (day_ago,)
    ).fetchall()

    if hot_threads:
        print(f"\n## TOP REPLY OPPORTUNITIES (score >= 3)")
        print("-" * 40)
        for t in hot_threads:
            print(f"  [{t['score']:>4} pts | {t['num_comments']:>3} comments] r/{t['subreddit']}")
            print(f"    {t['title'][:80]}")
            print(f"    {t['url']}")
            print()

    print("=" * 60)
    db.close()


def cmd_karma_update():
    """Update karma for our logged comments by re-fetching thread data."""
    db = get_db()
    comments = db.execute("SELECT id, thread_url, comment_text FROM comments").fetchall()

    if not comments:
        print("no comments to update")
        return

    print(f"checking karma for {len(comments)} comments...")
    updated = 0

    for comment in comments:
        url = comment["thread_url"]
        if not url:
            continue

        json_url = url.rstrip("/") + ".json"
        data = curl_json(json_url)

        if data is None or not isinstance(data, list) or len(data) < 2:
            continue

        comment_text_lower = comment["comment_text"].lower().strip()
        comments_data = data[1].get("data", {}).get("children", [])

        for rc in comments_data:
            rc_data = rc.get("data", {})
            rc_body = (rc_data.get("body", "") or "").lower().strip()

            # fuzzy match: check if first 50 chars match
            if rc_body[:50] == comment_text_lower[:50] and len(comment_text_lower) > 10:
                karma = rc_data.get("score", 0)
                db.execute(
                    "UPDATE comments SET last_karma = ?, last_checked = ? WHERE id = ?",
                    (karma, datetime.utcnow().isoformat(), comment["id"])
                )
                updated += 1
                break

        time.sleep(2)

    db.commit()
    print(f"updated karma for {updated}/{len(comments)} comments")
    db.close()


def analyze_comment_traits(text):
    """Extract traits from comment text."""
    word_count = len(text.split())
    has_number = any(char.isdigit() for char in text)
    has_question = "?" in text
    humor_words = ["lol", "lmao", "honestly", "somehow", "literally", "apparently"]
    has_humor = any(w in text.lower() for w in humor_words)

    # structure analysis
    sentences = text.count(".") + text.count("!") + text.count("?")
    starts_lowercase = text[0].islower() if text else False

    # punchline: does last sentence feel like a payoff
    lines = [l.strip() for l in text.replace(".", "\n").replace("!", "\n").replace("?", "\n").split("\n") if l.strip()]
    has_punchline = len(lines) >= 2  # multi-sentence = setup/payoff potential

    return {
        "word_count": word_count,
        "has_number": has_number,
        "has_question": has_question,
        "has_humor": has_humor,
        "sentences": sentences,
        "starts_lowercase": starts_lowercase,
        "has_punchline": has_punchline,
    }


def cmd_learn():
    """Analyze what works and what doesn't across all dimensions."""
    db = get_db()
    all_comments = db.execute("SELECT * FROM comments ORDER BY last_karma DESC").fetchall()

    if not all_comments:
        print("no comments to analyze")
        return

    print("=" * 60)
    print("FEEDBACK LOOP ANALYSIS")
    print("=" * 60)

    thresholds = SCORING.get("learn_thresholds", {})
    winner_min = thresholds.get("winner_min_karma", 2)
    dud_max = thresholds.get("dud_max_karma", 1)

    avg_karma = sum(c["last_karma"] for c in all_comments) / len(all_comments)
    winners = [c for c in all_comments if c["last_karma"] > avg_karma and c["last_karma"] > winner_min]
    losers = [c for c in all_comments if c["last_karma"] <= dud_max]

    print(f"\n  total comments: {len(all_comments)}")
    print(f"  avg karma: {avg_karma:.1f}")
    print(f"  winners (above avg): {len(winners)}")
    print(f"  duds (0-1 karma): {len(losers)}")

    # === CONTENT ANALYSIS ===
    print(f"\n## CONTENT ANALYSIS")
    print("-" * 40)
    for label, group in [("WINNERS", winners), ("DUDS", losers)]:
        if not group:
            continue
        print(f"\n  {label}:")
        for c in group:
            text = c["comment_text"]
            traits = analyze_comment_traits(text)
            trait_tags = []
            if traits["has_number"]: trait_tags.append("numbers")
            if traits["has_humor"]: trait_tags.append("humor")
            if traits["has_punchline"]: trait_tags.append("punchline")
            if traits["has_question"]: trait_tags.append("question")
            if traits["word_count"] < 25: trait_tags.append("short")
            elif traits["word_count"] < 50: trait_tags.append("medium")
            else: trait_tags.append("long")

            print(f"    [{c['last_karma']:>3} karma] {text[:70].replace(chr(10), ' ')}...")
            print(f"      content: {', '.join(trait_tags) if trait_tags else 'none detected'}")

    # === TIMING ANALYSIS ===
    has_timing = any(c["hour_utc"] for c in all_comments)
    if has_timing:
        print(f"\n## TIMING ANALYSIS")
        print("-" * 40)

        # by day of week
        day_karma = {}
        for c in all_comments:
            day = c["day_of_week"] or "unknown"
            if day not in day_karma:
                day_karma[day] = []
            day_karma[day].append(c["last_karma"])
        print("  by day:")
        for day, karmas in sorted(day_karma.items(), key=lambda x: -sum(x[1])/len(x[1]) if x[1] else 0):
            avg = sum(karmas) / len(karmas)
            print(f"    {day}: avg {avg:.1f} karma ({len(karmas)} comments)")

        # by hour
        hour_karma = {}
        for c in all_comments:
            h = c["hour_utc"]
            if h is not None:
                bucket = f"{(h // 4) * 4:02d}-{(h // 4) * 4 + 3:02d} UTC"
                if bucket not in hour_karma:
                    hour_karma[bucket] = []
                hour_karma[bucket].append(c["last_karma"])
        if hour_karma:
            print("  by time block:")
            for bucket, karmas in sorted(hour_karma.items()):
                avg = sum(karmas) / len(karmas)
                print(f"    {bucket}: avg {avg:.1f} karma ({len(karmas)} comments)")

    # === THREAD CONTEXT ANALYSIS ===
    has_context = any(c["thread_score_at_reply"] for c in all_comments)
    if has_context:
        print(f"\n## THREAD CONTEXT")
        print("-" * 40)

        # by reply position
        pos_karma = {}
        for c in all_comments:
            pos = c["reply_position"] or "unknown"
            if pos not in pos_karma:
                pos_karma[pos] = []
            pos_karma[pos].append(c["last_karma"])
        print("  by reply position:")
        for pos in ["early", "mid", "late", "buried", "unknown"]:
            if pos in pos_karma:
                karmas = pos_karma[pos]
                avg = sum(karmas) / len(karmas)
                print(f"    {pos}: avg {avg:.1f} karma ({len(karmas)} comments)")

        # thread score correlation
        print("  by thread score at time of reply:")
        score_buckets = {"0-10": [], "10-100": [], "100-500": [], "500+": []}
        for c in all_comments:
            s = c["thread_score_at_reply"] or 0
            if s < 10: score_buckets["0-10"].append(c["last_karma"])
            elif s < 100: score_buckets["10-100"].append(c["last_karma"])
            elif s < 500: score_buckets["100-500"].append(c["last_karma"])
            else: score_buckets["500+"].append(c["last_karma"])
        for bucket, karmas in score_buckets.items():
            if karmas:
                avg = sum(karmas) / len(karmas)
                print(f"    thread {bucket} pts: avg {avg:.1f} karma ({len(karmas)} comments)")

        # thread age correlation
        print("  by thread age when replied:")
        age_buckets = {"<1h": [], "1-4h": [], "4-12h": [], "12-24h": [], "24h+": []}
        for c in all_comments:
            age = c["thread_age_hours"] or 0
            if age < 1: age_buckets["<1h"].append(c["last_karma"])
            elif age < 4: age_buckets["1-4h"].append(c["last_karma"])
            elif age < 12: age_buckets["4-12h"].append(c["last_karma"])
            elif age < 24: age_buckets["12-24h"].append(c["last_karma"])
            else: age_buckets["24h+"].append(c["last_karma"])
        for bucket, karmas in age_buckets.items():
            if karmas:
                avg = sum(karmas) / len(karmas)
                print(f"    {bucket}: avg {avg:.1f} karma ({len(karmas)} comments)")

    # === SUBREDDIT ANALYSIS ===
    has_subs = any(c["subreddit"] for c in all_comments)
    if has_subs:
        print(f"\n## SUBREDDIT PERFORMANCE")
        print("-" * 40)
        sub_karma = {}
        for c in all_comments:
            sub = c["subreddit"] or "unknown"
            if sub not in sub_karma:
                sub_karma[sub] = []
            sub_karma[sub].append(c["last_karma"])
        for sub, karmas in sorted(sub_karma.items(), key=lambda x: -sum(x[1])/len(x[1]) if x[1] else 0):
            avg = sum(karmas) / len(karmas)
            total = sum(karmas)
            print(f"  r/{sub}: avg {avg:.1f}, total {total} ({len(karmas)} comments)")

    # === PATTERN SUMMARY ===
    # compute traits once, reuse for console output and patterns.json
    w_traits = [analyze_comment_traits(c["comment_text"]) for c in winners] if winners else []
    l_traits = [analyze_comment_traits(c["comment_text"]) for c in losers] if losers else []
    key_learnings = []

    print(f"\n## LEARNED RULES")
    print("-" * 40)
    if w_traits:
        w_avg_len = sum(t["word_count"] for t in w_traits) / len(w_traits)
        w_pct_numbers = sum(1 for t in w_traits if t["has_number"]) / len(w_traits) * 100
        w_pct_humor = sum(1 for t in w_traits if t["has_humor"]) / len(w_traits) * 100
        w_pct_punchline = sum(1 for t in w_traits if t["has_punchline"]) / len(w_traits) * 100

        print(f"  content:")
        print(f"    winning word count: ~{w_avg_len:.0f} words")
        print(f"    winners with numbers: {w_pct_numbers:.0f}%")
        print(f"    winners with humor: {w_pct_humor:.0f}%")
        print(f"    winners with punchline: {w_pct_punchline:.0f}%")

        key_learnings.append(f"winning word count: ~{w_avg_len:.0f} words")
        if w_pct_humor > 30:
            key_learnings.append(f"humor present in {w_pct_humor:.0f}% of winners")
        if w_pct_punchline > 50:
            key_learnings.append(f"punchline structure in {w_pct_punchline:.0f}% of winners")
        if w_pct_numbers > 40:
            key_learnings.append(f"specific numbers in {w_pct_numbers:.0f}% of winners")

        if l_traits:
            l_avg_len = sum(t["word_count"] for t in l_traits) / len(l_traits)
            print(f"    loser word count: ~{l_avg_len:.0f} words")
            if abs(w_avg_len - l_avg_len) > 5:
                key_learnings.append(f"winners ~{w_avg_len:.0f} words vs duds ~{l_avg_len:.0f} words")

    # timing rules
    if has_context:
        early = [c["last_karma"] for c in all_comments if c["reply_position"] == "early"]
        late = [c["last_karma"] for c in all_comments if c["reply_position"] in ("late", "buried")]
        if early and late:
            e_avg = sum(early) / len(early)
            l_avg = sum(late) / len(late)
            print(f"  timing:")
            print(f"    early replies avg: {e_avg:.1f} karma")
            print(f"    late replies avg: {l_avg:.1f} karma")
            if e_avg > l_avg * 1.5:
                key_learnings.append(f"early replies avg {e_avg:.1f} karma vs late {l_avg:.1f}")

    # timing patterns for key_learnings
    if has_timing:
        day_karma = {}
        for c in all_comments:
            day = c["day_of_week"] or "unknown"
            if day not in day_karma:
                day_karma[day] = []
            day_karma[day].append(c["last_karma"])
        if day_karma:
            best_day = max(day_karma.items(), key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0)
            worst_day = min(day_karma.items(), key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0)
            if best_day[0] != worst_day[0] and len(best_day[1]) >= 2:
                best_avg = sum(best_day[1]) / len(best_day[1])
                worst_avg = sum(worst_day[1]) / len(worst_day[1])
                if best_avg > worst_avg * 1.5:
                    key_learnings.append(f"best day: {best_day[0]} (avg {best_avg:.1f}), worst: {worst_day[0]} (avg {worst_avg:.1f})")

    # subreddit patterns for key_learnings
    if has_subs:
        sub_karma = {}
        for c in all_comments:
            sub = c["subreddit"] or "unknown"
            if sub not in sub_karma:
                sub_karma[sub] = []
            sub_karma[sub].append(c["last_karma"])
        subs_with_data = {s: k for s, k in sub_karma.items() if len(k) >= 2}
        if subs_with_data:
            best_sub = max(subs_with_data.items(), key=lambda x: sum(x[1])/len(x[1]))
            best_sub_avg = sum(best_sub[1]) / len(best_sub[1])
            if best_sub_avg > avg_karma * 1.3:
                key_learnings.append(f"best subreddit: r/{best_sub[0]} (avg {best_sub_avg:.1f} karma, {len(best_sub[1])} comments)")

    print("=" * 60)

    # write patterns.json for programmatic access
    patterns = {
        "generated_at": datetime.utcnow().isoformat(),
        "stats": {
            "total_comments": len(all_comments),
            "avg_karma": round(avg_karma, 1),
            "winners_count": len(winners),
            "duds_count": len(losers),
        },
        "winners": [
            {
                "karma": c["last_karma"],
                "subreddit": c["subreddit"] or "unknown",
                "preview": c["comment_text"][:100],
                "traits": analyze_comment_traits(c["comment_text"]),
            }
            for c in winners[:20]
        ],
        "floppers": [
            {
                "karma": c["last_karma"],
                "subreddit": c["subreddit"] or "unknown",
                "preview": c["comment_text"][:100],
                "traits": analyze_comment_traits(c["comment_text"]),
            }
            for c in losers[:20]
        ],
        "key_learnings": key_learnings,
    }

    patterns_path = SCRIPT_DIR / "patterns.json"
    with open(patterns_path, "w") as f:
        json.dump(patterns, f, indent=2)
    print(f"\npatterns written to {patterns_path}")

    db.close()


def cmd_check(accounts=None):
    """Fetch karma for all comments from Reddit user profiles. Auto-syncs new comments."""
    db = get_db()
    target_accounts = accounts or ACCOUNTS

    for username in target_accounts:
        print(f"\n{'=' * 50}")
        print(f"  @{username}")
        print(f"{'=' * 50}")

        url = f"https://www.reddit.com/user/{username}/comments.json?limit=100&sort=new"
        data = curl_json(url)

        if data is None:
            print(f"  error: could not fetch profile for u/{username}")
            continue

        comments = data.get("data", {}).get("children", [])
        if not comments:
            print(f"  no comments found")
            continue

        synced = 0
        updated = 0

        for c in comments:
            cd = c.get("data", {})
            reddit_id = cd.get("id", "")
            body = cd.get("body", "")
            score = cd.get("score", 0)
            subreddit = cd.get("subreddit", "")
            thread_title = cd.get("link_title", "")
            permalink = cd.get("permalink", "")
            link_permalink = cd.get("link_permalink", "")
            created = cd.get("created_utc", 0)
            thread_url = f"https://www.reddit.com{link_permalink}" if link_permalink else ""

            # check if already in DB by reddit_comment_id
            existing = db.execute(
                "SELECT id FROM comments WHERE reddit_comment_id = ?", (reddit_id,)
            ).fetchone()

            if existing:
                # update karma
                db.execute(
                    "UPDATE comments SET last_karma = ?, last_checked = ? WHERE reddit_comment_id = ?",
                    (score, datetime.utcnow().isoformat(), reddit_id)
                )
                updated += 1
            else:
                # try matching by comment text (for manually logged comments without reddit_id)
                text_match = db.execute(
                    "SELECT id FROM comments WHERE comment_text = ? OR "
                    "(LENGTH(comment_text) > 20 AND SUBSTR(comment_text, 1, 50) = SUBSTR(?, 1, 50))",
                    (body, body)
                ).fetchone()

                if text_match:
                    db.execute(
                        "UPDATE comments SET last_karma = ?, last_checked = ?, "
                        "reddit_comment_id = ?, account = ? WHERE id = ?",
                        (score, datetime.utcnow().isoformat(), reddit_id, username, text_match["id"])
                    )
                    updated += 1
                else:
                    # auto-sync: new comment not in DB
                    posted_at = datetime.utcfromtimestamp(created).isoformat() if created else datetime.utcnow().isoformat()
                    mentioned = 1 if any(kw in body.lower() for kw in MENTION_KEYWORDS) else 0
                    db.execute(
                        "INSERT INTO comments (thread_url, comment_text, posted_at, last_karma, "
                        "last_checked, mentioned_product, subreddit, account, reddit_comment_id, thread_title) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (thread_url, body, posted_at, score,
                         datetime.utcnow().isoformat(), mentioned,
                         subreddit, username, reddit_id, thread_title)
                    )
                    synced += 1

        db.commit()

        # enrich thread context for comments that haven't been enriched yet
        # NOTE: backfilled data reflects thread state at enrichment time, not at
        # reply time. thread_score/comments may be higher than when you actually
        # replied. Data from cmd_log is exact; data from enrichment is approximate.
        missing_context = db.execute(
            "SELECT id, thread_url, posted_at FROM comments "
            "WHERE account = ? AND thread_url != '' AND "
            "(context_enriched IS NULL OR context_enriched = 0) "
            "ORDER BY posted_at DESC LIMIT 10",
            (username,)
        ).fetchall()

        if missing_context:
            enriched = 0
            for mc in missing_context:
                json_url = mc["thread_url"].rstrip("/") + ".json"
                tdata = curl_json(json_url)
                if tdata and isinstance(tdata, list) and len(tdata) >= 1:
                    post = tdata[0].get("data", {}).get("children", [{}])[0].get("data", {})
                    thread_score = post.get("score", 0)
                    thread_comments = post.get("num_comments", 0)
                    created = post.get("created_utc", 0)
                    thread_age = 0
                    if created:
                        try:
                            posted = datetime.fromisoformat(mc["posted_at"])
                            thread_age = (posted.timestamp() - created) / 3600
                        except (ValueError, TypeError):
                            pass

                    if thread_comments < 10:
                        position = "early"
                    elif thread_comments < 50:
                        position = "mid"
                    elif thread_comments < 200:
                        position = "late"
                    else:
                        position = "buried"

                    db.execute(
                        "UPDATE comments SET thread_score_at_reply = ?, "
                        "thread_comments_at_reply = ?, thread_age_hours = ?, "
                        "reply_position = ?, context_enriched = 1 WHERE id = ?",
                        (thread_score, thread_comments, round(thread_age, 1),
                         position, mc["id"])
                    )
                    enriched += 1
                else:
                    # mark as enriched even on failure so we don't retry forever
                    db.execute(
                        "UPDATE comments SET context_enriched = 1 WHERE id = ?",
                        (mc["id"],)
                    )
                time.sleep(1)

            if enriched:
                db.commit()
                print(f"  enriched thread context for {enriched} comments")

        # now display results
        all_user_comments = db.execute(
            "SELECT * FROM comments WHERE account = ? ORDER BY posted_at DESC",
            (username,)
        ).fetchall()

        total_karma = sum(c["last_karma"] for c in all_user_comments)
        print(f"  total comments: {len(all_user_comments)} | total karma: {total_karma}")
        print(f"  synced {synced} new | updated {updated} existing")
        print()

        # show recent comments with karma
        for c in all_user_comments[:15]:
            age = ""
            try:
                posted = datetime.fromisoformat(c["posted_at"])
                hours_ago = (datetime.utcnow() - posted).total_seconds() / 3600
                if hours_ago < 24:
                    age = f"{hours_ago:.0f}h ago"
                else:
                    age = f"{hours_ago/24:.0f}d ago"
            except (ValueError, TypeError):
                age = "?"

            title = (c["thread_title"] or "")[:50]
            preview = c["comment_text"][:60].replace("\n", " ")
            sub = c["subreddit"] or "?"
            print(f"  [{c['last_karma']:>3} pts] r/{sub} ({age}) — {title}")
            print(f"          {preview}")
            print()

        time.sleep(2)

    db.close()


def cmd_find(sort=None, limit=None):
    """Find karma-farming opportunities across big subs. Focus on momentum, not keywords."""
    sort = sort or FIND_SETTINGS.get("default_sort", "rising")
    limit = limit or FIND_SETTINGS.get("result_limit", 15)
    max_age = FIND_SETTINGS.get("max_age_hours", 3)
    max_comments = FIND_SETTINGS.get("max_comments", 50)
    max_score = FIND_SETTINGS.get("max_score", 3000)

    now = time.time()
    all_posts = []

    for sub in KARMA_FARMING_SUBS:
        url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit=25"
        data = curl_json(url)
        if data is None:
            continue

        for p in data.get("data", {}).get("children", []):
            d = p.get("data", {})
            age_h = (now - d.get("created_utc", now)) / 3600
            score = d.get("score", 0)
            num_comments = d.get("num_comments", 0)

            # momentum filter: fresh + growing + not saturated
            if age_h > max_age:
                continue
            if num_comments > max_comments:
                continue
            if score > max_score:
                continue

            # calculate momentum score
            velocity = score / max(age_h, 0.1)  # pts per hour
            comment_ratio = score / max(num_comments, 1)
            momentum = velocity * (comment_ratio ** 0.5)  # reward high ratio

            permalink = d.get("permalink", "")
            all_posts.append({
                "sub": d.get("subreddit", sub),
                "title": d.get("title", "")[:80],
                "score": score,
                "comments": num_comments,
                "age_h": round(age_h, 1),
                "velocity": round(velocity),
                "ratio": round(comment_ratio, 1),
                "momentum": round(momentum),
                "url": f"https://reddit.com{permalink}",
                "selftext": (d.get("selftext") or "")[:200],
                "is_self": d.get("is_self", False),
            })

        time.sleep(1)

    all_posts.sort(key=lambda x: x["momentum"], reverse=True)

    # build account-to-subreddit mapping for suggestions
    account_subs = {}
    raw_accounts = CONFIG.get("accounts", [])
    if raw_accounts and isinstance(raw_accounts[0], dict):
        for a in raw_accounts:
            account_subs[a["username"]] = [s.lower() for s in a.get("subreddits", [])]

    def suggest_account(subreddit):
        """Suggest which account fits this subreddit, or None for general."""
        if not account_subs:
            return None
        sub_lower = subreddit.lower()
        matches = [name for name, subs in account_subs.items() if sub_lower in subs]
        if len(matches) == 1:
            return matches[0]
        return None  # general sub or multiple matches

    print(f"{'=' * 60}")
    print(f"KARMA FARMING OPPORTUNITIES — {datetime.utcnow().strftime('%H:%M UTC')}")
    print(f"{'=' * 60}")
    print(f"filter: <{max_age}h old, <{max_comments} comments, <{max_score} score, sorted by momentum\n")

    top_posts = all_posts[:limit]
    preview_limit = FIND_SETTINGS.get("preview_comments", 3)

    for i, p in enumerate(top_posts, 1):
        acct = suggest_account(p['sub'])
        acct_tag = f" → @{acct}" if acct else ""
        print(f"{i:>2}. [{p['score']}pts / {p['comments']}c / {p['age_h']}h] r/{p['sub']}{acct_tag}")
        print(f"    velocity: {p['velocity']} pts/h | ratio: {p['ratio']} | momentum: {p['momentum']}")
        print(f"    {p['title']}")
        if p['selftext']:
            print(f"    > {p['selftext'][:120]}...")
        print(f"    {p['url']}")

        if preview_limit > 0:
            comments = fetch_top_comments(p['url'], limit=preview_limit)
            if comments:
                print(f"    --- top comments ---")
                for score, text in comments:
                    print(f"    [{score:>3}] {text}")
            time.sleep(0.5)

        print()


def cmd_stats():
    """Quick stats summary."""
    db = get_db()
    total_threads = db.execute("SELECT COUNT(*) as c FROM threads").fetchone()["c"]
    total_comments = db.execute("SELECT COUNT(*) as c FROM comments").fetchone()["c"]
    total_karma = db.execute("SELECT COALESCE(SUM(last_karma), 0) as s FROM comments").fetchone()["s"]

    day_ago = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    new_today = db.execute("SELECT COUNT(*) as c FROM threads WHERE seen_at > ?", (day_ago,)).fetchone()["c"]

    print(f"threads tracked: {total_threads} ({new_today} new today)")
    print(f"comments logged: {total_comments}")
    print(f"total karma: {total_karma}")
    db.close()


def main():
    init()

    if len(sys.argv) < 2:
        print("usage:")
        print("  python3 reddit_tracker.py check               - fetch karma from Reddit profiles (auto-sync)")
        print("  python3 reddit_tracker.py find                 - find karma-farming opportunities")
        print("  python3 reddit_tracker.py fetch                - discover new niche threads (keyword-based)")
        print("  python3 reddit_tracker.py log <url> <text>     - log a posted comment")
        print("  python3 reddit_tracker.py report               - full performance report")
        print("  python3 reddit_tracker.py karma                - update karma (old method, use check instead)")
        print("  python3 reddit_tracker.py stats                - quick stats")
        print("  python3 reddit_tracker.py learn                - feedback loop analysis")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        accounts = sys.argv[2:] if len(sys.argv) > 2 else None
        cmd_check(accounts)
    elif cmd == "find":
        sort = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_find(sort=sort)
    elif cmd == "fetch":
        cmd_fetch()
    elif cmd == "log":
        if len(sys.argv) < 4:
            print("usage: python3 reddit_tracker.py log <thread_url> <comment_text>")
            sys.exit(1)
        cmd_log(sys.argv[2], sys.argv[3])
    elif cmd == "report":
        cmd_report()
    elif cmd == "karma":
        cmd_karma_update()
    elif cmd == "stats":
        cmd_stats()
    elif cmd == "learn":
        cmd_learn()
    else:
        print(f"unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
