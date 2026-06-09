"""
Reusable prompt templates for all AI analysis tasks.

Design principles:
  - Factual, no financial advice
  - Concise output (low token count)
  - Strict JSON output to avoid parsing failures
  - Configurable via variables — never hardcoded inline

Two modes:
  WEB_SEARCH_*  — used when OpenAI has the web_search_preview tool available.
                  The model is asked to *search first* then analyse.
  NEWS_ANALYSIS_* — fallback when only pre-fetched headlines are supplied.
"""

# ── System prompts ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a crypto market intelligence analyst. Your job is to research recent
news for a specific cryptocurrency and produce a structured, factual market
intelligence report.

Rules:
- Search for the most recent news (last 24 hours if possible).
- Be factual and concise.
- Do NOT give financial advice or price predictions.
- Focus on market-moving events: regulation, ETF news, adoption, exchange
  listings, partnerships, hacks, macro trends, whale movements.
- If little news is available, reflect that with low confidence.
- Output ONLY valid JSON — no prose, no markdown fences.
- Sentiment values: exactly "bullish", "bearish", or "neutral".
- Confidence: integer 0–100.
"""

# ── Web-search prompt (PRIMARY) ───────────────────────────────────────────────
# Instructs the model to SEARCH the web first, then produce the analysis.
# The model receives the web_search_preview tool and should use it before
# generating the JSON response.

WEB_SEARCH_ANALYSIS_PROMPT = """\
Search the web for the latest news about {coin_name} ({symbol}) cryptocurrency
published in the last 24 hours.

After reviewing the search results, return ONLY this JSON object — no other text:

{{
  "summary": "<2–3 sentences capturing the key market narrative>",
  "sentiment": "<bullish|bearish|neutral>",
  "confidence": <0-100>,
  "positive_factors": ["<factor>", ...],
  "negative_factors": ["<factor>", ...],
  "market_impact": "<1–2 sentences on likely short-term market effect>",
  "key_events": ["<event>", ...],
  "sources": [
    {{"title": "<headline>", "url": "<url>"}},
    ...
  ]
}}

- positive_factors: up to 4 bullish catalysts you found
- negative_factors: up to 4 bearish risks you found
- key_events: up to 4 notable events from the news
- sources: up to 5 news articles you used (include URL where available)
- If no significant news exists, set sentiment to "neutral" and confidence to 10.
"""

# ── Fallback prompt (when web search is unavailable) ─────────────────────────
# Used only when OpenAI key works but the Responses API is not available.

NEWS_ANALYSIS_PROMPT = """\
Analyse the following {n} recent news items for {coin_name} ({symbol}).

News items (title | description snippet):
{news_block}

Return ONLY this JSON object:
{{
  "summary": "<2–3 sentences capturing the key market narrative>",
  "sentiment": "<bullish|bearish|neutral>",
  "confidence": <0-100>,
  "positive_factors": ["<factor>", ...],
  "negative_factors": ["<factor>", ...],
  "market_impact": "<1–2 sentences on likely short-term market effect>",
  "key_events": ["<event>", ...],
  "sources": []
}}
"""

NO_NEWS_PROMPT = """\
There are no recent news articles available for {coin_name} ({symbol}).

Return ONLY this JSON object:
{{
  "summary": "No significant news found for {symbol} in the last 24 hours.",
  "sentiment": "neutral",
  "confidence": 0,
  "positive_factors": [],
  "negative_factors": [],
  "market_impact": "Insufficient data to assess market impact.",
  "key_events": [],
  "sources": []
}}
"""


def build_news_block(articles: list[dict]) -> str:
    """
    Compact news text block for the fallback path.
    Each line: [{i+1}] title | description[:120]
    """
    lines = []
    for i, art in enumerate(articles, 1):
        title = art.get("title", "").strip()
        desc = (art.get("description") or "").strip()
        snippet = desc[:120] if desc else ""
        line = f"[{i}] {title}" + (f" | {snippet}" if snippet else "")
        lines.append(line)
    return "\n".join(lines)
