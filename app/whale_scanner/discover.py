"""Discover token candidates added in the last N days."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.providers.dexscreener_boosts_provider import DexScreenerBoostsProvider
from app.discovery.providers.gecko_new_pools_provider import GeckoNewPoolsProvider
from app.discovery.scoring.growth_scorer import MAX_AGE_HOURS_NEW, passes_hard_filters
from app.discovery.services.discovery_service import discovery_service
from app.discovery.types import DiscoveryToken
from app.models.whale_scan import WhaleScanCandidate
from app.whale_scanner.settings import whale_scan_settings

logger = logging.getLogger(__name__)


@dataclass
class RawCandidate:
    chain: str
    contract_address: str
    symbol: str
    token_name: str
    source: str
    age_hours: float
    liquidity_usd: float
    volume_24h: float
    dex: str = ""


def _token_to_raw(token: DiscoveryToken, source: str) -> RawCandidate | None:
    if token.source_type == "cex" or not token.contract_address:
        return None
    chain = (token.chain or "").lower().strip()
    address = (token.contract_address or "").strip()
    if not chain or not address:
        return None
    return RawCandidate(
        chain=chain,
        contract_address=address,
        symbol=(token.symbol or "").upper()[:32],
        token_name=(token.token_name or token.symbol or "")[:128],
        source=source,
        age_hours=float(token.age_hours or 0),
        liquidity_usd=float(token.liquidity or 0),
        volume_24h=float(token.volume_24h or 0),
        dex=(token.dex or "")[:64],
    )


async def _fetch_discovery_tokens() -> list[DiscoveryToken]:
    tokens: list[DiscoveryToken] = []

    for category in ("new_dex", "surging", "trending"):
        try:
            result = await discovery_service.get_by_category(category, refresh=True, limit=80)
            tokens.extend(result.items)
            logger.info("Discovery %s: %d tokens", category, len(result.items))
        except Exception as exc:
            logger.warning("Discovery category %s failed: %s", category, exc)

    gecko = GeckoNewPoolsProvider()
    dex_boosts = DexScreenerBoostsProvider()
    extra = await asyncio.gather(
        gecko.fetch(limit=120),
        dex_boosts.fetch(limit=60),
        return_exceptions=True,
    )
    for label, batch in zip(("gecko_new_pools", "dexscreener_boosts"), extra):
        if isinstance(batch, Exception):
            logger.warning("Provider %s failed: %s", label, batch)
            continue
        tokens.extend(batch)
        logger.info("Provider %s: %d tokens", label, len(batch))

    return tokens


def _filter_candidates(raw_list: list[RawCandidate]) -> list[RawCandidate]:
    max_age = min(whale_scan_settings.max_age_hours, MAX_AGE_HOURS_NEW)
    min_liq = whale_scan_settings.MIN_LIQUIDITY_USD
    min_vol = whale_scan_settings.MIN_VOLUME_24H

    seen: set[str] = set()
    filtered: list[RawCandidate] = []

    for raw in raw_list:
        key = f"{raw.chain}:{raw.contract_address.lower()}"
        if key in seen:
            continue
        seen.add(key)

        if raw.age_hours > max_age and raw.age_hours > 0:
            continue
        if raw.liquidity_usd < min_liq and raw.volume_24h < min_vol:
            continue
        filtered.append(raw)

    filtered.sort(key=lambda c: c.volume_24h, reverse=True)
    return filtered[: whale_scan_settings.MAX_TOKENS_PER_RUN * 2]


async def discover_raw_candidates() -> list[RawCandidate]:
    """Fetch and filter on-chain token candidates."""
    tokens = await _fetch_discovery_tokens()
    raw_list: list[RawCandidate] = []
    for token in tokens:
        if not passes_hard_filters(token):
            continue
        raw = _token_to_raw(token, source=token.discovery_category or token.source or "discovery")
        if raw:
            raw_list.append(raw)
    return _filter_candidates(raw_list)


async def upsert_candidates(
    db: AsyncSession,
    raw_list: list[RawCandidate],
) -> list[WhaleScanCandidate]:
    """Persist candidates; return rows eligible for scanning this run."""
    now = datetime.now(timezone.utc)
    rows: list[WhaleScanCandidate] = []

    for raw in raw_list:
        result = await db.execute(
            select(WhaleScanCandidate).where(
                WhaleScanCandidate.chain == raw.chain,
                WhaleScanCandidate.contract_address == raw.contract_address,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.last_seen_at = now
            row.symbol = raw.symbol or row.symbol
            row.token_name = raw.token_name or row.token_name
            row.source = raw.source
            row.liquidity_usd = raw.liquidity_usd
            row.volume_24h = raw.volume_24h
            row.age_hours = raw.age_hours
            row.dex = raw.dex or row.dex
        else:
            row = WhaleScanCandidate(
                chain=raw.chain,
                contract_address=raw.contract_address,
                symbol=raw.symbol,
                token_name=raw.token_name,
                source=raw.source,
                first_seen_at=now,
                last_seen_at=now,
                liquidity_usd=raw.liquidity_usd,
                volume_24h=raw.volume_24h,
                age_hours=raw.age_hours,
                dex=raw.dex,
            )
            db.add(row)
        rows.append(row)

    await db.flush()
    return rows


async def select_scan_batch(db: AsyncSession) -> list[WhaleScanCandidate]:
    """Pick candidates to scan — never scanned first, then stalest."""
    max_age = whale_scan_settings.max_age_hours
    first_seen_cutoff = datetime.now(timezone.utc) - timedelta(days=whale_scan_settings.MAX_AGE_DAYS)

    result = await db.execute(
        select(WhaleScanCandidate)
        .where(
            or_(
                WhaleScanCandidate.age_hours <= max_age,
                WhaleScanCandidate.age_hours <= 0,
                WhaleScanCandidate.first_seen_at >= first_seen_cutoff,
            )
        )
        .order_by(
            WhaleScanCandidate.last_scanned_at.asc().nullsfirst(),
            WhaleScanCandidate.volume_24h.desc(),
        )
        .limit(whale_scan_settings.MAX_TOKENS_PER_RUN)
    )
    return list(result.scalars().all())
