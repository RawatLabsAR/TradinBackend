"""
OpenAI async client wrapper — two entry points:

1. chat_json()          → Chat Completions + JSON mode (fast, no live web data)
2. web_search_analyze() → Responses API + web_search_preview tool
                          OpenAI *searches the web* for recent crypto news and
                          then generates a structured market analysis — all in
                          one API call.  This is the primary path for AI insights.
"""

import json
import logging
import re
from typing import Optional

from openai import AsyncOpenAI, APIStatusError, RateLimitError, APIConnectionError

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def get_client() -> Optional[AsyncOpenAI]:
    global _client
    if _client is None and settings.OPENAI_API_KEY:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Optional[dict]:
    """
    Try to parse JSON from the model's response text.
    Handles the common cases where the model wraps JSON in markdown fences
    (```json ... ```) or outputs it inline.
    """
    # Strip markdown fences if present
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    raw = fenced.group(1) if fenced else text.strip()

    # Find first { ... } block
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# web_search_analyze — PRIMARY path for AI insights
# ---------------------------------------------------------------------------

async def web_search_analyze(
    symbol: str,
    coin_name: str,
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
) -> tuple[Optional[dict], int, int]:
    """
    Use OpenAI Responses API with the web_search_preview tool.

    OpenAI searches the live web for recent news about the coin, incorporates
    those search results into its context, and then generates a structured
    market analysis — all in a single API call.

    Returns (parsed_dict, prompt_tokens, completion_tokens).
    Returns (None, 0, 0) on any failure so callers can fall back gracefully.
    """
    client = get_client()
    if client is None:
        logger.warning("OpenAI client not initialised — OPENAI_API_KEY missing")
        return None, 0, 0

    chosen_model = model or settings.AI_MODEL or "gpt-4o-mini"

    try:
        response = await client.responses.create(
            model=chosen_model,
            tools=[{"type": "web_search_preview"}],
            instructions=system_prompt,
            input=user_prompt,
        )

        usage = response.usage
        prompt_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "output_tokens", 0) if usage else 0

        raw_text = response.output_text or ""
        logger.debug("OpenAI web_search response for %s: %d chars", symbol, len(raw_text))

        parsed = _extract_json(raw_text)
        if parsed is None:
            logger.error(
                "OpenAI web_search response for %s was not valid JSON. Raw: %s",
                symbol,
                raw_text[:300],
            )
            return None, prompt_tokens, completion_tokens

        return parsed, prompt_tokens, completion_tokens

    except RateLimitError:
        logger.error("OpenAI rate limit exceeded — will retry on next cycle")
        return None, 0, 0
    except APIStatusError as exc:
        logger.error("OpenAI API error %d: %s", exc.status_code, exc.message)
        return None, 0, 0
    except APIConnectionError as exc:
        logger.error("OpenAI connection error: %s", exc)
        return None, 0, 0
    except Exception as exc:
        logger.error("Unexpected OpenAI error: %s", exc)
        return None, 0, 0


# ---------------------------------------------------------------------------
# chat_json — kept for lightweight use-cases (no live web search)
# ---------------------------------------------------------------------------

async def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    max_tokens: int = 600,
    temperature: float = 0.2,
) -> tuple[Optional[dict], int, int]:
    """
    Chat Completions with JSON mode.  No live web search — suitable for
    tasks that already have all the context supplied in the prompt.
    """
    client = get_client()
    if client is None:
        logger.warning("OpenAI client not initialised — OPENAI_API_KEY missing")
        return None, 0, 0

    chosen_model = model or settings.AI_MODEL or "gpt-4o-mini"

    try:
        response = await client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=temperature,
        )

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        raw_content = response.choices[0].message.content or ""
        parsed = json.loads(raw_content)
        return parsed, prompt_tokens, completion_tokens

    except RateLimitError:
        logger.error("OpenAI rate limit exceeded")
        return None, 0, 0
    except APIStatusError as exc:
        logger.error("OpenAI API error %d: %s", exc.status_code, exc.message)
        return None, 0, 0
    except APIConnectionError as exc:
        logger.error("OpenAI connection error: %s", exc)
        return None, 0, 0
    except json.JSONDecodeError as exc:
        logger.error("OpenAI response was not valid JSON: %s", exc)
        return None, 0, 0
    except Exception as exc:
        logger.error("Unexpected OpenAI error: %s", exc)
        return None, 0, 0
