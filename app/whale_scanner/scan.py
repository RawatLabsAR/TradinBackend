"""On-chain trade sync + whale detection per candidate."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.whale_scan import WhaleScanCandidate
from app.onchain.analytics.whale_detector import detect_whale_events
from app.onchain.models.entities import WhaleWallet
from app.onchain.pipelines.etl_pipeline import sync_token_trades
from app.onchain.types import normalize_address
from app.whale_scanner.settings import whale_scan_settings

logger = logging.getLogger(__name__)


@dataclass
class TokenScanResult:
    candidate: WhaleScanCandidate
    events: list[WhaleWallet] = field(default_factory=list)
    trades_inserted: int = 0
    error: str | None = None

    @property
    def max_usd(self) -> float:
        if not self.events:
            return 0.0
        return max(e.usd_value for e in self.events)

    @property
    def score(self) -> float:
        if not self.events:
            return 0.0
        buy_types = {"LARGE_BUY", "ACCUMULATION", "COORDINATED_ACTIVITY"}
        buys = sum(1 for e in self.events if e.event_type in buy_types)
        return self.max_usd + buys * 10_000


async def _scan_one(
    db: AsyncSession,
    candidate: WhaleScanCandidate,
) -> TokenScanResult:
    chain = candidate.chain.lower()
    address = normalize_address(chain, candidate.contract_address)
    result = TokenScanResult(candidate=candidate)

    try:
        trades = await sync_token_trades(db, chain, address, max_pages=3)
        result.trades_inserted = int(trades.get("inserted") or 0)

        events = await detect_whale_events(
            db,
            chain,
            address,
            hours=whale_scan_settings.WHALE_LOOKBACK_HOURS,
            threshold_usd=whale_scan_settings.WHALE_THRESHOLD_USD,
        )
        result.events = events
        candidate.last_scanned_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "Scanned %s/%s… — %d trades, %d whale events",
            chain,
            address[:10],
            result.trades_inserted,
            len(events),
        )
    except Exception as exc:
        result.error = str(exc)
        await db.rollback()
        logger.exception("Scan failed %s/%s: %s", chain, address, exc)

    return result


async def scan_candidates(
    session_factory: async_sessionmaker,
    candidates: list[WhaleScanCandidate],
) -> list[TokenScanResult]:
    """Scan tokens with bounded concurrency and API-friendly delays."""
    if not candidates:
        return []

    sem = asyncio.Semaphore(whale_scan_settings.SCAN_CONCURRENCY)
    delay = whale_scan_settings.SCAN_DELAY_MS / 1000.0
    results: list[TokenScanResult] = []

    async def worker(candidate: WhaleScanCandidate) -> TokenScanResult:
        async with sem:
            async with session_factory() as db:
                out = await _scan_one(db, candidate)
            if delay > 0:
                await asyncio.sleep(delay)
            return out

    tasks = [asyncio.create_task(worker(c)) for c in candidates]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    for item in gathered:
        if isinstance(item, Exception):
            logger.error("Scan worker error: %s", item)
            continue
        results.append(item)
    return results


def rank_results(results: list[TokenScanResult]) -> list[TokenScanResult]:
    """Tokens with whale activity, highest score first."""
    hits = [r for r in results if r.events]
    hits.sort(key=lambda r: r.score, reverse=True)
    return hits
