"""
Message formatter for Telegram.

Produces Telegram Markdown v1-compatible strings.
All signal/AI/news templates live here so dispatchers stay
transport-agnostic (they just call format_* and pass the string along).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional


def _escape_md(text: str) -> str:
    """Escape characters that Telegram Markdown v1 treats as special."""
    # Only * _ ` [ are special in Markdown v1 mode inside a non-code span
    return re.sub(r"([_*\[\]`\\])", r"\\\1", str(text))


def _price(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= 1_000:
        return f"${value:,.2f}"
    return f"${value:.4f}"


def format_signal_alert(
    symbol: str,
    signal_type: str,
    strategy: str,
    timeframe: str,
    price: float | None,
    reason: Optional[str] = None,
    sentiment: Optional[str] = None,
    ai_commentary: Optional[str] = None,
) -> str:
    """
    Format a strategy signal into a rich Telegram Markdown message.

    Example output:
    🚀 *BUY SIGNAL — BTC-USD*
    ───────────────────────────────
    📊 *Strategy:* EMA Cross
    ⏱ *Timeframe:* 15m
    💰 *Entry Price:* $109,240.00
    ...
    """
    sig = signal_type.upper()
    if sig == "BUY":
        emoji = "🚀"
    elif sig == "SELL":
        emoji = "🔴"
    elif sig == "EXIT":
        emoji = "🚪"
    else:
        emoji = "⚡"

    sentiment_emoji = ""
    if sentiment:
        s = sentiment.lower()
        if "bull" in s or s == "positive":
            sentiment_emoji = "📈"
        elif "bear" in s or s == "negative":
            sentiment_emoji = "📉"
        else:
            sentiment_emoji = "➡️"

    lines = [
        f"{emoji} *{sig} SIGNAL — {_escape_md(symbol)}*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *Strategy:* {_escape_md(strategy)}",
        f"⏱ *Timeframe:* {_escape_md(timeframe)}",
        f"💰 *Price:* {_price(price)}",
    ]
    if reason:
        lines += ["", "📝 *Reason:*", _escape_md(reason)]
    if sentiment:
        lines += [
            "",
            f"{sentiment_emoji} *AI Sentiment:* {_escape_md(sentiment.capitalize())}",
        ]
    if ai_commentary:
        lines += ["", f"🤖 _{_escape_md(ai_commentary)}_"]

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines += ["", f"🕐 _{ts}_"]

    return "\n".join(lines)


def format_ai_insight(
    symbol: str,
    summary: str,
    sentiment: Optional[str] = None,
    confidence: Optional[float] = None,
    drivers: Optional[list[str]] = None,
) -> str:
    """Format an AI market insight broadcast."""
    sentiment_emoji = "🧠"
    if sentiment:
        s = sentiment.lower()
        if "bull" in s or s == "positive":
            sentiment_emoji = "📈"
        elif "bear" in s or s == "negative":
            sentiment_emoji = "📉"

    lines = [
        f"{sentiment_emoji} *AI Market Insight — {_escape_md(symbol)}*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        _escape_md(summary),
    ]
    if sentiment:
        conf_str = f" \\({int(confidence or 0)}%\\)" if confidence else ""
        lines += ["", f"*Sentiment:* {_escape_md(sentiment.capitalize())}{conf_str}"]
    if drivers:
        lines += ["", "*Key Drivers:*"]
        for d in drivers[:5]:
            lines.append(f"  • {_escape_md(d)}")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines += ["", f"🕐 _{ts}_"]

    return "\n".join(lines)


def format_custom_message(content: str, parse_mode: str = "Markdown") -> str:
    """
    Pass-through for manually composed messages.
    Validates length compliance (Telegram limit: 4096 chars).
    """
    if len(content) > 4096:
        content = content[:4090] + "\n…"
    return content


def render_template(template: str, variables: dict[str, Any]) -> str:
    """
    Replace {{variable}} placeholders in a template string.

    Variables dict keys must match placeholders (case-insensitive).
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        val = variables.get(key, variables.get(key.upper(), f"[{key}]"))
        return str(val)

    result = re.sub(r"\{\{(\w+)\}\}", replacer, template)
    return result[:4096] if len(result) > 4096 else result


def format_system_notification(title: str, body: str, level: str = "info") -> str:
    icons = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "success": "✅"}
    icon = icons.get(level, "ℹ️")
    return f"{icon} *{_escape_md(title)}*\n\n{_escape_md(body)}"
