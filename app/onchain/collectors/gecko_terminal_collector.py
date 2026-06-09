"""GeckoTerminal free API collector — OHLCV history and live pool trades."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.onchain.collectors.base_collector import BaseCollector
from app.onchain.collectors.base import api_request
from app.onchain.types import NormalizedOhlcv, NormalizedTrade, normalize_address

logger = logging.getLogger(__name__)

GECKO_API_BASE = "https://api.geckoterminal.com/api/v2"
GECKO_HEADERS = {"Accept": "application/json;version=20230203"}
MAX_OHLCV_RANGE_DAYS = 180
MAX_OHLCV_PAGES = 5

CHAIN_TO_NETWORK = {
    "ethereum": "eth",
    "base": "base",
    "bsc": "bsc",
    "solana": "solana",
}


def _to_network(chain: str) -> str:
    network = CHAIN_TO_NETWORK.get(chain.lower())
    if not network:
        raise ValueError(f"GeckoTerminal: unsupported chain '{chain}'")
    return network


def _pick_ohlcv_params(span_days: int) -> tuple[str, int]:
    if span_days <= 7:
        return "hour", 1
    if span_days <= 90:
        return "hour", 4
    return "day", 1


class GeckoTerminalCollector(BaseCollector):
    source_name = "geckoterminal"

    async def resolve_pool(
        self,
        chain: str,
        token_address: str,
    ) -> Optional[dict]:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        network = _to_network(chain)

        resp = await api_request(
            "GET",
            f"{GECKO_API_BASE}/networks/{network}/tokens/{token_address}/pools",
            source="geckoterminal",
            headers=GECKO_HEADERS,
            cache_key=f"gecko:pools:{network}:{token_address}",
            cache_ttl=86400,
            min_interval_ms=1200,
        )

        if not isinstance(resp, dict):
            return None

        pools = resp.get("data") or []
        if not pools:
            return None

        def _score(item: dict) -> float:
            attrs = item.get("attributes") or {}
            reserve = float(attrs.get("reserve_in_usd") or 0)
            vol = float((attrs.get("volume_usd") or {}).get("h24") or 0)
            return reserve * 0.6 + vol * 0.4

        best = max(pools, key=_score)
        attrs = best.get("attributes") or {}
        dex_id = ""
        rel = best.get("relationships") or {}
        dex_data = (rel.get("dex") or {}).get("data") or {}
        if isinstance(dex_data, dict):
            dex_id = str(dex_data.get("id") or "")

        return {
            "pool_address": str(attrs.get("address") or ""),
            "dex": dex_id.replace("-", " "),
            "reserve_in_usd": float(attrs.get("reserve_in_usd") or 0),
            "price_usd": float(attrs.get("token_price_usd") or 0),
            "volume_h24_usd": float((attrs.get("volume_usd") or {}).get("h24") or 0),
            "txns_h24": attrs.get("transactions") or {},
        }

    async def fetch_ohlcv_range(
        self,
        chain: str,
        token_address: str,
        *,
        start: datetime,
        end: datetime,
        pool: Optional[dict] = None,
    ) -> list[NormalizedOhlcv]:
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        if pool is None:
            pool = await self.resolve_pool(chain, token_address)
        if not pool or not pool.get("pool_address"):
            logger.warning("GeckoTerminal: no pool for %s/%s", chain, token_address[:12])
            return []

        span_days = max(1, (end - start).days + 1)
        if span_days > MAX_OHLCV_RANGE_DAYS:
            start = end - timedelta(days=MAX_OHLCV_RANGE_DAYS)

        timeframe, aggregate = _pick_ohlcv_params(span_days)
        network = _to_network(chain)
        pool_address = pool["pool_address"]

        # Estimate candles needed — usually one API call is enough
        if timeframe == "day":
            est_candles = span_days + 2
        elif aggregate > 1:
            est_candles = min(span_days * (24 // aggregate) + 4, 1000)
        else:
            est_candles = min(span_days * 24 + 4, 1000)

        candles: list[NormalizedOhlcv] = []
        seen_ts: set[int] = set()
        before_ts = int(end.timestamp()) + 86400
        start_ts = int(start.timestamp())

        for page in range(MAX_OHLCV_PAGES):
            params = {
                "aggregate": aggregate,
                "limit": min(est_candles, 1000),
                "before_timestamp": before_ts,
            }
            resp = await api_request(
                "GET",
                f"{GECKO_API_BASE}/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}",
                source="geckoterminal",
                params=params,
                headers=GECKO_HEADERS,
                min_interval_ms=2100,
            )

            if not isinstance(resp, dict):
                break

            ohlcv_list = ((resp.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            if not ohlcv_list:
                break

            oldest_ts = None
            for row in ohlcv_list:
                if not isinstance(row, (list, tuple)) or len(row) < 6:
                    continue
                ts = int(row[0])
                if ts in seen_ts:
                    continue
                if ts < start_ts:
                    continue
                if ts > int(end.timestamp()) + 86400:
                    continue

                seen_ts.add(ts)
                oldest_ts = ts if oldest_ts is None else min(oldest_ts, ts)
                candles.append(NormalizedOhlcv(
                    chain=chain,
                    token_address=token_address,
                    pool_address=pool_address,
                    timeframe=timeframe,
                    aggregate=aggregate,
                    timestamp=datetime.utcfromtimestamp(ts),
                    open_usd=float(row[1]),
                    high_usd=float(row[2]),
                    low_usd=float(row[3]),
                    close_usd=float(row[4]),
                    volume_usd=float(row[5]),
                    raw_source=self.source_name,
                    metadata={"page": page},
                ))

            if oldest_ts is None or oldest_ts <= start_ts:
                break
            before_ts = oldest_ts

        logger.info(
            "GeckoTerminal OHLCV: %s/%s fetched %d candles (%s agg=%d)",
            chain, token_address[:10], len(candles), timeframe, aggregate,
        )
        return candles

    async def fetch_ohlcv_live(
        self,
        chain: str,
        token_address: str,
        *,
        start: datetime,
        end: datetime,
        pool: Optional[dict] = None,
    ) -> list[NormalizedOhlcv]:
        """Single API call — fast path for live analysis UI."""
        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        if pool is None:
            pool = await self.resolve_pool(chain, token_address)
        if not pool or not pool.get("pool_address"):
            return []

        span_days = max(1, (end - start).days + 1)
        if span_days > MAX_OHLCV_RANGE_DAYS:
            start = end - timedelta(days=MAX_OHLCV_RANGE_DAYS)

        timeframe, aggregate = _pick_ohlcv_params(span_days)
        network = _to_network(chain)
        pool_address = pool["pool_address"]
        start_ts = int(start.timestamp())

        if timeframe == "day":
            limit = min(span_days + 5, 1000)
        elif aggregate > 1:
            limit = min(span_days * (24 // aggregate) + 8, 1000)
        else:
            limit = min(span_days * 24 + 8, 1000)

        resp = await api_request(
            "GET",
            f"{GECKO_API_BASE}/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}",
            source="geckoterminal",
            params={
                "aggregate": aggregate,
                "limit": limit,
                "before_timestamp": int(end.timestamp()) + 86400,
            },
            headers=GECKO_HEADERS,
            min_interval_ms=1200,
        )

        if not isinstance(resp, dict):
            return []

        ohlcv_list = ((resp.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        candles: list[NormalizedOhlcv] = []
        end_ts = int(end.timestamp()) + 86400

        for row in ohlcv_list:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            ts = int(row[0])
            if ts < start_ts or ts > end_ts:
                continue
            candles.append(NormalizedOhlcv(
                chain=chain,
                token_address=token_address,
                pool_address=pool_address,
                timeframe=timeframe,
                aggregate=aggregate,
                timestamp=datetime.utcfromtimestamp(ts),
                open_usd=float(row[1]),
                high_usd=float(row[2]),
                low_usd=float(row[3]),
                close_usd=float(row[4]),
                volume_usd=float(row[5]),
                raw_source=self.source_name,
            ))

        candles.sort(key=lambda c: c.timestamp)
        logger.info("GeckoTerminal live OHLCV: %s/%s → %d candles (1 request)", chain, token_address[:10], len(candles))
        return candles

    async def fetch_trades(
        self,
        chain: str,
        token_address: str,
        *,
        since: Optional[datetime] = None,
        cursor: str = "",
        limit: int = 100,
        pool: Optional[dict] = None,
    ) -> tuple[list[NormalizedTrade], str]:
        if cursor:
            return [], ""

        chain = chain.lower()
        token_address = normalize_address(chain, token_address)
        if pool is None:
            pool = await self.resolve_pool(chain, token_address)
        if not pool or not pool.get("pool_address"):
            return [], ""

        network = _to_network(chain)
        resp = await api_request(
            "GET",
            f"{GECKO_API_BASE}/networks/{network}/pools/{pool['pool_address']}/trades",
            source="geckoterminal",
            params={"limit": min(limit, 300)},
            headers=GECKO_HEADERS,
            cache_key=f"gecko:trades:{network}:{pool['pool_address']}",
            cache_ttl=60,
            min_interval_ms=1200,
        )

        if not isinstance(resp, dict):
            return [], ""

        trades: list[NormalizedTrade] = []
        for item in resp.get("data") or []:
            attrs = item.get("attributes") or {}
            ts = self._parse_ts(attrs.get("block_timestamp"))
            if since and ts < since:
                continue

            kind = str(attrs.get("kind") or "").lower()
            side = "BUY" if kind == "buy" else "SELL"
            token_lower = token_address.lower() if token_address.startswith("0x") else token_address
            to_addr = str(attrs.get("to_token_address") or "")
            from_addr = str(attrs.get("from_token_address") or "")

            if side == "BUY" and to_addr.lower() != token_lower and to_addr != token_address:
                if from_addr.lower() == token_lower or from_addr == token_address:
                    side = "SELL"
                else:
                    continue

            usd = float(attrs.get("volume_in_usd") or 0)
            if usd <= 0:
                continue

            price = float(attrs.get("price_to_in_usd") or attrs.get("price_from_in_usd") or 0)
            trades.append(NormalizedTrade(
                chain=chain,
                token_address=token_address,
                wallet=str(attrs.get("tx_from_address") or "unknown"),
                side=side,
                amount=float(attrs.get("to_token_amount") or attrs.get("from_token_amount") or 0),
                usd_value=usd,
                timestamp=ts,
                dex=pool.get("dex") or "",
                tx_hash=str(attrs.get("tx_hash") or ""),
                block_number=int(attrs.get("block_number") or 0) or None,
                price_usd=price or None,
                raw_source=self.source_name,
                metadata={"pool": pool["pool_address"]},
            ))

        return trades[:limit], ""
