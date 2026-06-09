"""Dune Analytics API collector for Ethereum and Base DEX swaps."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.onchain.collectors.base_collector import BaseCollector
from app.onchain.collectors.base import api_request
from app.onchain.normalizers.trade_normalizer import normalize_dune_trade
from app.onchain.normalizers.liquidity_normalizer import normalize_dune_liquidity
from app.onchain.types import NormalizedLiquidityEvent, NormalizedTrade, normalize_address

logger = logging.getLogger(__name__)

DUNE_API_BASE = "https://api.dune.com/api/v1"


class DuneCollector(BaseCollector):
    source_name = "dune"

    def __init__(self) -> None:
        self._api_key = settings.DUNE_API_KEY

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {"X-Dune-Api-Key": self._api_key}

    async def _run_sql_and_wait(
        self,
        sql: str,
        *,
        cache_key: Optional[str] = None,
        poll_seconds: int = 120,
    ) -> list[dict]:
        """Execute SQL via Dune API and poll until results are ready."""
        if not self.is_configured:
            logger.debug("DuneCollector: DUNE_API_KEY not set")
            return []

        exec_resp = await api_request(
            "POST",
            f"{DUNE_API_BASE}/sql/execute",
            source="dune",
            json_body={"sql": sql},
            headers=self._headers(),
            min_interval_ms=1000,
        )

        if isinstance(exec_resp, dict) and exec_resp.get("error"):
            err = str(exec_resp.get("error", ""))
            if "performance tier" in err.lower():
                exec_resp = await api_request(
                    "POST",
                    f"{DUNE_API_BASE}/sql/execute",
                    source="dune",
                    json_body={"sql": sql, "performance": "small"},
                    headers=self._headers(),
                    min_interval_ms=1000,
                )

        if not isinstance(exec_resp, dict):
            return []

        if exec_resp.get("error"):
            logger.warning(
                "Dune SQL execute failed (status=%s): %s",
                exec_resp.get("status"),
                str(exec_resp.get("error"))[:300],
            )
            return []

        execution_id = exec_resp.get("execution_id")
        if not execution_id:
            # Some responses include rows directly
            rows = (exec_resp.get("result") or {}).get("rows", [])
            if rows:
                return rows
            logger.warning("Dune SQL missing execution_id: keys=%s", list(exec_resp.keys()))
            return []

        logger.info("Dune SQL execution started: %s", execution_id)

        results_url = f"{DUNE_API_BASE}/execution/{execution_id}/results"
        max_attempts = max(poll_seconds // 2, 15)

        for attempt in range(max_attempts):
            if attempt > 0:
                await asyncio.sleep(2)

            results = await api_request(
                "GET",
                results_url,
                source="dune",
                headers=self._headers(),
                min_interval_ms=500,
                cache_key=cache_key if attempt == max_attempts - 1 else None,
                cache_ttl=120,
            )

            if not isinstance(results, dict):
                continue

            if results.get("error"):
                logger.warning("Dune results error: %s", str(results.get("error"))[:200])
                return []

            state = results.get("state", "")
            if state == "QUERY_STATE_COMPLETED":
                rows = (results.get("result") or {}).get("rows", [])
                logger.info("Dune SQL completed: %d rows", len(rows))
                return rows if isinstance(rows, list) else []

            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED"):
                logger.warning("Dune SQL %s: %s", state, results.get("error", ""))
                return []

        logger.warning("Dune SQL timed out after %ds (execution=%s)", poll_seconds, execution_id)
        return []

    @staticmethod
    def _sql_address(token_address: str) -> str:
        addr = token_address.lower().strip()
        if not addr.startswith("0x"):
            addr = f"0x{addr}"
        return addr

    async def fetch_trades(
        self,
        chain: str,
        token_address: str,
        *,
        since: Optional[datetime] = None,
        cursor: str = "",
        limit: int = 100,
    ) -> tuple[list[NormalizedTrade], str]:
        if not self.is_configured:
            return [], ""

        if chain not in ("ethereum", "base"):
            return [], ""

        token_address = normalize_address(chain, token_address)
        addr = self._sql_address(token_address)

        if since:
            since_clause = f"block_time >= from_unixtime({int(since.timestamp())})"
        else:
            # Default: last 7 days to keep queries fast
            since_dt = datetime.utcnow() - timedelta(days=7)
            since_clause = f"block_time >= from_unixtime({int(since_dt.timestamp())})"

        offset = int(cursor or "0")
        blockchain = chain
        limit_clause = f"LIMIT {limit + offset}" if offset else f"LIMIT {limit}"

        sql = f"""
        SELECT
            blockchain,
            tx_hash,
            block_time,
            taker AS wallet,
            project AS dex,
            token_bought_address,
            token_sold_address,
            token_bought_amount,
            token_sold_amount,
            amount_usd,
            block_number
        FROM dex.trades
        WHERE blockchain = '{blockchain}'
          AND {since_clause}
          AND (
            token_bought_address = {addr}
            OR token_sold_address = {addr}
          )
        ORDER BY block_time DESC
        {limit_clause}
        """

        cache_key = f"dune:trades:{chain}:{addr}:{offset}:{limit}"
        rows = await self._run_sql_and_wait(sql, cache_key=cache_key)
        if offset:
            rows = rows[offset:offset + limit]

        trades = [normalize_dune_trade(row, chain, token_address) for row in rows]
        trades = [t for t in trades if t]
        next_cursor = str(offset + len(rows)) if len(rows) >= limit else ""
        return trades, next_cursor

    async def fetch_liquidity_events(
        self,
        chain: str,
        token_address: str,
        *,
        since: Optional[datetime] = None,
        cursor: str = "",
        limit: int = 100,
    ) -> tuple[list[NormalizedLiquidityEvent], str]:
        if not self.is_configured or chain not in ("ethereum", "base"):
            return [], ""

        token_address = normalize_address(chain, token_address)
        addr = self._sql_address(token_address)

        if since:
            since_clause = f"block_time >= from_unixtime({int(since.timestamp())})"
        else:
            since_dt = datetime.utcnow() - timedelta(days=7)
            since_clause = f"block_time >= from_unixtime({int(since_dt.timestamp())})"

        sql = f"""
        SELECT
            tx_hash,
            block_time,
            contract_address AS pool_address,
            amount_usd,
            evt_type,
            project AS dex
        FROM dex.liquidity
        WHERE blockchain = '{chain}'
          AND {since_clause}
        ORDER BY block_time DESC
        LIMIT {limit}
        """

        rows = await self._run_sql_and_wait(
            sql,
            cache_key=f"dune:liq:{chain}:{addr}:{limit}",
        )
        events = [normalize_dune_liquidity(row, chain, token_address) for row in rows]
        return [e for e in events if e], ""
