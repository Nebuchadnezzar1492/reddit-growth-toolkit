#!/usr/bin/env python3
"""Rocket Thread Scanner — finds high-score/low-comment Reddit threads.

Scans 40+ subreddits for "rocket threads" where the score/comment ratio
is extreme, indicating massive visibility with almost no competition.

Usage:
    python3 rocket-scanner.py                  # scan all personas
    python3 rocket-scanner.py persona_name     # scan one persona
    python3 rocket-scanner.py --json           # output as JSON
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ─── CONFIG ───────────────────────────────────────────────────────────
CONFIG = {
    "min_ratio": 10,            # score / max(comments, 1)
    "min_velocity": 1.5,        # points per minute
    "max_age_minutes": 50,      # thread must be younger than this
    "max_comments": 20,         # hard cap on comments
    "request_delay": 2.5,       # seconds between API calls
    "user_agent": "RocketScanner/1.0",
    "sort": "rising",           # which reddit endpoint to hit
    "limit": 25,                # posts per subreddit
    "retry_after_429": 60,      # seconds to wait on rate limit
}

# ─── PERSONAS & SUBREDDITS ────────────────────────────────────────────
# Load from local config if it exists (gitignored), otherwise use defaults.
# To customize: copy scripts/personas.example.py → scripts/personas.local.py
# and edit with your own persona names and subreddits.

import os as _os
import importlib.util as _ilu

_LOCAL_PERSONAS_PATH = _os.path.join(_os.path.dirname(__file__), "personas.local.py")

def _load_personas():
    if _os.path.exists(_LOCAL_PERSONAS_PATH):
        spec = _ilu.spec_from_file_location("personas_local", _LOCAL_PERSONAS_PATH)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.PERSONAS
    # Default example personas — customize via personas.local.py
    return {
        "tech_builder": {
            "niche": [
                "selfhosted", "homelab", "docker", "linux",
                "HomeNetworking", "sysadmin",
            ],
            "builder": [
                "DIY", "3Dprinting", "HomeImprovement",
                "tools", "BuyItForLife",
            ],
            "general": [
                "AskReddit", "technology", "mildlyinfuriating",
                "unpopularopinion", "pcmasterrace", "buildapc",
                "CasualConversation", "NoStupidQuestions", "TIFU",
                "MaliciousCompliance", "Wellthatsucks", "LifeProTips",
                "todayilearned", "explainlikeimfive", "personalfinance",
                "Frugal", "gadgets", "antiwork", "Futurology",
            ],
        },
        "privacy_advocate": {
            "niche": [
                "privacy", "degoogle", "privacytoolsIO", "selfhosted",
                "GDPR", "datahoarder",
            ],
            "general": [
                "AskReddit", "technology", "mildlyinfuriating",
                "unpopularopinion", "NoStupidQuestions", "CasualConversation",
                "LifeProTips", "antiwork", "Futurology", "TIFU",
                "MaliciousCompliance", "Wellthatsucks", "todayilearned",
                "explainlikeimfive", "meirl",
            ],
        },
    }

PERSONAS = _load_personas()


def all_subs_for_persona(persona):
    """Get flat list of subs for a persona."""
    groups = PERSONAS.get(persona, {})
    subs = []
    for group in groups.values():
        subs.extend(group)
    return subs


def all_unique_subs():
    """Get deduplicated set of all subreddits across all personas."""
    subs = set()
    for persona in PERSONAS.values():
        for group in persona.values():
            subs.update(group)
    return sorted(subs)


def persona_for_sub(sub):
    """Return list of personas that include this subreddit."""
    matches = []
    for name, groups in PERSONAS.items():
        for group in groups.values():
            if sub in group:
                matches.append(name)
                break
    return matches


# ─── REDDIT API ───────────────────────────────────────────────────────
def fetch_rising(sub):
    """Fetch rising posts for a subreddit. Returns list of post data dicts."""
    url = (
        f"https://www.reddit.com/r/{sub}/{CONFIG['sort']}.json"
        f"?limit={CONFIG['limit']}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": CONFIG["user_agent"]})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return [child["data"] for child in data.get("data", {}).get("children", [])]
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  [429] Rate limited on r/{sub}, waiting {CONFIG['retry_after_429']}s...", file=sys.stderr)
            time.sleep(CONFIG["retry_after_429"])
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    return [child["data"] for child in data.get("data", {}).get("children", [])]
            except Exception:
                return []
        elif e.code in (403, 404):
            print(f"  [!] r/{sub} returned {e.code}, skipping", file=sys.stderr)
            return []
        else:
            print(f"  [!] r/{sub} HTTP {e.code}, skipping", file=sys.stderr)
            return []
    except Exception as e:
        print(f"  [!] r/{sub} error: {e}", file=sys.stderr)
        return []


def score_post(post):
    """Evaluate a post against rocket criteria. Returns enriched dict or None."""
    # skip stickied/pinned
    if post.get("stickied") or post.get("pinned"):
        return None

    now = datetime.now(timezone.utc).timestamp()
    created = post.get("created_utc", now)
    age_min = max((now - created) / 60, 0.5)
    score = post.get("score", 0)
    comments = post.get("num_comments", 0)

    ratio = score / max(comments, 1)
    velocity = score / age_min

    # apply filters
    if age_min > CONFIG["max_age_minutes"]:
        return None
    if comments > CONFIG["max_comments"]:
        return None
    if ratio < CONFIG["min_ratio"]:
        return None
    if velocity < CONFIG["min_velocity"]:
        return None
    if score < 5:
        return None

    sub = post.get("subreddit", "unknown")
    permalink = post.get("permalink", "")

    return {
        "subreddit": sub,
        "title": post.get("title", ""),
        "score": score,
        "comments": comments,
        "age_min": round(age_min),
        "ratio": round(ratio, 1),
        "velocity": round(velocity, 1),
        "url": f"https://www.reddit.com{permalink}",
        "personas": persona_for_sub(sub),
        "selftext_preview": (post.get("selftext", "") or "")[:150],
    }


# ─── SCANNER ──────────────────────────────────────────────────────────
def scan(persona_filter=None):
    """Scan subreddits and return rocket threads grouped by persona.

    Args:
        persona_filter: If set, only scan subs for this persona.

    Returns:
        dict: {"persona_name": [...], ...}
    """
    if persona_filter and persona_filter in PERSONAS:
        subs_to_scan = sorted(set(all_subs_for_persona(persona_filter)))
    else:
        subs_to_scan = all_unique_subs()

    total = len(subs_to_scan)
    rockets = []

    for i, sub in enumerate(subs_to_scan):
        print(f"  Scanning r/{sub} ({i+1}/{total})...", file=sys.stderr, end="", flush=True)
        posts = fetch_rising(sub)
        found = 0
        for post in posts:
            result = score_post(post)
            if result:
                rockets.append(result)
                found += 1
        print(f" {found} rockets" if found else " -", file=sys.stderr)

        if i < total - 1:
            time.sleep(CONFIG["request_delay"])

    # group by persona
    grouped = {name: [] for name in PERSONAS}
    for r in rockets:
        for p in r["personas"]:
            if persona_filter and p != persona_filter:
                continue
            grouped[p].append(r)

    # sort each group by ratio descending
    for name in grouped:
        grouped[name].sort(key=lambda x: x["ratio"], reverse=True)

    return grouped


def format_output(results):
    """Format results for terminal display."""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("  ROCKET THREADS")
    lines.append("=" * 60)

    total = sum(len(v) for v in results.values())

    if total == 0:
        lines.append("")
        lines.append("  No rockets found. Try again during peak hours (US morning-evening).")
        lines.append("")
        return "\n".join(lines)

    for persona, threads in results.items():
        if not threads:
            continue
        lines.append("")
        lines.append(f"  --- {persona} ({len(threads)} rockets) ---")
        lines.append("")
        for i, t in enumerate(threads, 1):
            lines.append(f"  [{i}] r/{t['subreddit']} | {t['title'][:70]}")
            lines.append(
                f"      Score: {t['score']} | Cmts: {t['comments']} | "
                f"Ratio: {t['ratio']} | Vel: {t['velocity']}pts/min | "
                f"Age: {t['age_min']}min"
            )
            lines.append(f"      {t['url']}")
            if t["selftext_preview"]:
                lines.append(f"      {t['selftext_preview'][:100]}")
            lines.append("")

    lines.append("=" * 60)
    lines.append(f"  Total: {total} rockets across {len([v for v in results.values() if v])} personas")
    lines.append("=" * 60)
    lines.append("")

    return "\n".join(lines)


def to_json(results):
    """Return results as JSON string."""
    return json.dumps(results, indent=2, ensure_ascii=False)


# ─── CLI ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    persona_filter = None
    output_json = False

    for arg in sys.argv[1:]:
        if arg == "--json":
            output_json = True
        elif arg in PERSONAS:
            persona_filter = arg
        elif arg in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"Unknown argument: {arg}", file=sys.stderr)
            print(f"Usage: {sys.argv[0]} [persona_name] [--json]", file=sys.stderr)
            sys.exit(1)

    print(f"\nScanning {'all personas' if not persona_filter else persona_filter}...\n", file=sys.stderr)
    results = scan(persona_filter)

    if output_json:
        print(to_json(results))
    else:
        print(format_output(results))
