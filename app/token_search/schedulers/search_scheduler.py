"""Token search scheduler — DB-backed jobs only when persistence is enabled."""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def attach_token_search_scheduler(scheduler) -> None:
    if not settings.ENABLE_TOKEN_SEARCH_DB:
        logger.info("Token search DB disabled — no search scheduler jobs")
        return
    logger.info("Token search scheduler: trending is computed on-read (no background jobs)")
