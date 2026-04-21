#!/usr/bin/env python3
"""Rocket scanner + Telegram notification.

Runs the scanner and sends a Telegram message when rockets are found.
Designed to run as a cron job.

Setup:
    1. Create a Telegram bot via @BotFather, get the token
    2. Get your chat ID (message @userinfobot)
    3. Create scripts/notify.env with:
       TELEGRAM_BOT_TOKEN=your_token
       TELEGRAM_CHAT_ID=your_chat_id
    4. Add to crontab:
       */10 8-23 * * * cd /path/to/auto-commenter && python3 scripts/notify.py

Usage:
    python3 scripts/notify.py              # scan + notify
    python3 scripts/notify.py --test       # send test message
"""

import json
import os
import sys
import urllib.request
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, "notify.env")

def load_env():
    """Load TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from notify.env."""
    env = {}
    if not os.path.exists(ENV_PATH):
        print(f"ERROR: {ENV_PATH} not found. Create it with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.", file=sys.stderr)
        sys.exit(1)
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def send_telegram(token, chat_id, text):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Telegram send failed: {e}", file=sys.stderr)
        return None


def format_rocket_message(results):
    """Format rockets as a Telegram message."""
    lines = ["🚀 <b>ROCKETS FOUND</b>\n"]
    for persona, threads in results.items():
        if not threads:
            continue
        for t in threads:
            lines.append(
                f"<b>{persona}</b> → r/{t['subreddit']}\n"
                f"{t['title'][:60]}\n"
                f"Score:{t['score']} | Cmts:{t['comments']} | "
                f"Ratio:{t['ratio']} | Vel:{t['velocity']}pts/min\n"
                f"{t['url']}\n"
            )
    return "\n".join(lines)


def main():
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required in notify.env", file=sys.stderr)
        sys.exit(1)

    # Handle --test
    if "--test" in sys.argv:
        result = send_telegram(token, chat_id, "🚀 Rocket scanner test — notifications working!")
        if result and result.get("ok"):
            print("Test message sent successfully.")
        else:
            print("Test message failed.", file=sys.stderr)
        return

    # Run scanner
    sys.path.insert(0, SCRIPT_DIR)
    from importlib import import_module

    # Import rocket scanner dynamically to handle the personas.local.py loading
    import importlib.util
    scanner_path = os.path.join(SCRIPT_DIR, "rocket-scanner.py")
    spec = importlib.util.spec_from_file_location("rocket_scanner", scanner_path)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)

    results = scanner.scan()
    total = sum(len(v) for v in results.values())

    if total == 0:
        # No rockets — stay silent, don't spam
        return

    msg = format_rocket_message(results)
    send_telegram(token, chat_id, msg)
    print(f"Sent notification: {total} rockets found.")


if __name__ == "__main__":
    main()
