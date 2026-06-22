#!/usr/bin/env python3
"""Discover Telegram chat IDs via Bot API getUpdates (and optional getChat)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

API = "https://api.telegram.org/bot{token}/{method}"


def call(token: str, method: str, params: dict | None = None) -> dict:
    url = API.format(token=token, method=method)
    data = json.dumps(params or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=35) as resp:
        return json.loads(resp.read())


def extract_chats(updates: list) -> dict[int, dict]:
    seen: dict[int, dict] = {}
    for upd in updates:
        for key in ("message", "channel_post", "my_chat_member", "chat_member"):
            msg = upd.get(key)
            if not msg:
                continue
            chat = msg.get("chat") or (msg.get("new_chat_member") or {}).get("chat")
            if not chat:
                continue
            cid = chat.get("id")
            if cid and cid not in seen:
                seen[cid] = {
                    "chat_id": cid,
                    "title": chat.get("title") or chat.get("first_name") or str(cid),
                    "type": chat.get("type"),
                    "username": chat.get("username"),
                }
    return seen


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env first.", file=sys.stderr)
        return 1

    username = sys.argv[1].lstrip("@") if len(sys.argv) > 1 else None
    if username:
        data = call(token, "getChat", {"chat_id": f"@{username}"})
        if not data.get("ok"):
            print(f"getChat @{username} failed: {data.get('description')}", file=sys.stderr)
            return 1
        chat = data["result"]
        print(json.dumps(chat, indent=2))
        print(f"\nUse in .env: TELEGRAM_WHALE_CHANNEL_ID={chat['id']}")
        return 0

    print("Polling getUpdates for 30s — message your bot or post in a channel where it was added…")
    data = call(token, "getUpdates", {"timeout": 30, "limit": 100})
    if not data.get("ok"):
        print(f"getUpdates failed: {data.get('description')}", file=sys.stderr)
        return 1

    chats = extract_chats(data.get("result", []))
    if not chats:
        print(
            "No chats found.\n"
            "1. Add @Abhirawat27_bot to your channel as admin\n"
            "2. Post any message in the channel\n"
            "3. Re-run: python scripts/discover_telegram_chat.py\n"
            "Or resolve a public channel: python scripts/discover_telegram_chat.py @yourchannel"
        )
        return 1

    for chat in sorted(chats.values(), key=lambda c: str(c["title"])):
        print(json.dumps(chat, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
