"""
Built-in message templates for common broadcast scenarios.

These are the default templates seeded into the DB on first run.
"""
from __future__ import annotations

from typing import Any

DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Signal Alert",
        "category": "signal",
        "content": (
            "{{signal_emoji}} *{{signal_type}} SIGNAL — {{symbol}}*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 *Strategy:* {{strategy}}\n"
            "⏱ *Timeframe:* {{timeframe}}\n"
            "💰 *Price:* {{price}}\n\n"
            "📝 *Reason:*\n{{reason}}\n\n"
            "🤖 _{{ai_commentary}}_"
        ),
        "variables": ["signal_emoji", "signal_type", "symbol", "strategy",
                      "timeframe", "price", "reason", "ai_commentary"],
        "parse_mode": "Markdown",
    },
    {
        "name": "AI Market Insight",
        "category": "ai_insight",
        "content": (
            "🧠 *AI Market Insight — {{symbol}}*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "{{summary}}\n\n"
            "*Sentiment:* {{sentiment}}\n"
            "*Confidence:* {{confidence}}%"
        ),
        "variables": ["symbol", "summary", "sentiment", "confidence"],
        "parse_mode": "Markdown",
    },
    {
        "name": "Market Alert",
        "category": "alert",
        "content": (
            "⚠️ *Market Alert — {{symbol}}*\n\n"
            "{{message}}\n\n"
            "_{{timestamp}}_"
        ),
        "variables": ["symbol", "message", "timestamp"],
        "parse_mode": "Markdown",
    },
    {
        "name": "Breakout Alert",
        "category": "signal",
        "content": (
            "💥 *BREAKOUT — {{symbol}}*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Price just broke *{{level}}* resistance\n"
            "Current Price: {{price}}\n"
            "Volume: {{volume}}\n\n"
            "_{{timestamp}}_"
        ),
        "variables": ["symbol", "level", "price", "volume", "timestamp"],
        "parse_mode": "Markdown",
    },
    {
        "name": "Daily Summary",
        "category": "custom",
        "content": (
            "📅 *Daily Market Summary*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "{{content}}\n\n"
            "_Generated: {{timestamp}}_"
        ),
        "variables": ["content", "timestamp"],
        "parse_mode": "Markdown",
    },
]
