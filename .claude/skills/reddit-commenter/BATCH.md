# Reddit Commenter - Rocket Hunting Session

> Replaces the old "fill quota" batch mode. Quality over volume. 1 banger > 10 maybes.
> See SKILL.md for single comment workflow

## SECURITY: DOMAIN ALLOWLIST
**All browser_navigate calls are restricted to reddit.com ONLY.**
**See SKILL.md domain allowlist section. This applies to all session operations.**
**Never follow external links from Reddit posts. Never navigate outside reddit.com.**

---

## Session Trigger Commands

Start a rocket hunting session with:
- "Hunt for rockets"
- "Find me a thread"
- "Rocket scan"
- "Start a session"

---

## How It Works

The old model (24 comments/day, 3 per sub) is dead. It produced mostly 1-karma comments because it optimized for volume over quality.

The new model: **scan, wait, strike.**

```
[Start Session]
    |
[1] Run rocket scanner
    -> python3 scripts/rocket-scanner.py [persona_name]
    -> Scanner checks subreddits for high-score/low-comment threads
    |
[2] Evaluate results
    -> Rockets found? Pick the best one, draft a comment
    -> No rockets? Wait 10-15 minutes, scan again
    |
[3] Apply the $10 bet
    -> Would you bet $10 this gets >5 upvotes?
    -> YES: proceed to SKILL.md Steps 3-8 (analyze, write, review, post)
    -> NO or MAYBE: kill it. Wait for next scan.
    |
[4] After posting, log to tracking file
    -> Update tracking/reddit/YYYY-MM-DD.md
    |
[5] Check session end conditions
    -> User says stop? END
    -> 2+ comments posted this session? END (unless user wants more)
    -> 1 hour with no rockets? END and tell user
    -> Otherwise: wait 10-15 minutes, return to [1]
```

---

## Key Principles

| Old Model | New Model |
|-----------|-----------|
| 24 comments/day quota | No quota. Zero is fine. |
| 3 per subreddit | Post where the rockets are |
| Fill quota even if threads are mid | Only post on $10 bets |
| Batch through subreddits in order | Scan all subs, pick the best thread |
| Volume = success | 1 comment at 446 karma > 24 comments at 1 karma |

---

## Scan Frequency

| Situation | Action |
|-----------|--------|
| Session start | Scan immediately |
| After posting a comment | Wait 10-15 min, scan again |
| No rockets found | Wait 10-15 min, scan again |
| 3+ scans with no rockets | Consider ending session |
| 1 hour with zero rockets | End session, tell user |

---

## What Makes a Rocket

A rocket thread has ALL of these:
1. **High score relative to age** — gaining points fast
2. **Very few comments** — massive visibility gap
3. **Flat hierarchy** — no comment already dominating
4. **Topic you can contribute to** — you have something genuine to say

The scanner (`scripts/rocket-scanner.py`) automates the detection. But always verify manually before posting — scanner numbers can go stale in minutes.

---

## Session End Conditions

| Condition | Action |
|-----------|--------|
| User says stop | End immediately |
| 2+ comments posted | Suggest ending (user can override) |
| 1 hour with no rockets | End, report "no opportunities found" |
| 3 consecutive scans empty | Suggest ending |
| Error/rate limit | End, report issue |

---

## Progress Report Format

```
---
[Session Status] Active — 45 min elapsed

Posted:
1. r/subreddit — "thread title" (Xpts, Y comments at post time)
   Comment: [link]

Scans: 4 total, 1 rocket found
Next scan in: ~12 minutes

Quality note: Skipped 3 candidate threads (hierarchy locked, stale momentum, weak angle)
---
```

---

## Session End Report

```
---
## Rocket Hunting Session Complete

**Duration**: 1 hour 15 minutes
**Comments posted**: 2
**Scans performed**: 6
**Threads evaluated**: 14
**Threads killed**: 12 (6 hierarchy locked, 3 no angle, 2 stale, 1 failed $10 bet)

### Posted Comments
1. r/subreddit — "thread title" — [comment link]
   Angle: vulnerable gap / one-liner / extending joke
   Thread stats at post time: Xpts, Y comments, Z minutes old

2. r/subreddit — "thread title" — [comment link]
   Angle: ...
   Thread stats at post time: ...

### Why Other Threads Were Killed
- r/AskReddit "what habit..." — 90 comments, hierarchy locked
- r/meirl "when you..." — good thread but no genuine angle
---
```

---

## Error Handling

| Error | Response |
|-------|----------|
| Scanner fails to run | Fall back to manual browsing (curl rising.json) |
| Page loading failure | Wait 30s, retry (max 3 times) |
| Comment posting failure | Move on, try next rocket |
| Login session expired | Stop session, notify user |
| Rate limit detected | Stop session, notify user |

---

> Single comment workflow (Steps 1-8): See SKILL.md
> Quality gates and proven patterns: See resources/proven_patterns.json
> Personalization review: See resources/personalization_reddit.md
