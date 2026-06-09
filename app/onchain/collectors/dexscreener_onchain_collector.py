"""DexScreener fallback collector — pair stats and synthetic trade signals for EVM."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.onchain.collectors.base_collector import BaseCollector
from app.onchain.collectors.base import api_request
from app.token_search.types import normalize_chain
from app.onchain.types import NormalizedTrade, normalize_address

logger = logging.getLogger(__name__)


def _pair_volume(pair: dict, key: str) -> float:
    return float((pair.get("volume") or {}).get(key) or 0)


def _pair_txns(pair: dict, key: str) -> tuple[int, int]:
    txns = (pair.get("txns") or {}).get(key) or {}
    return int(txns.get("buys") or 0), int(txns.get("sells") or 0)


def _append_distributed_trades(
    trades: list[NormalizedTrade],
    *,
    chain: str,
    token_address: str,
    dex: str,
    price: float,
    volume_usd: float,
    buys: int,
    sells: int,
    end_offset: timedelta,
    window: timedelta,
    slots: int,
    window_id: str,
) -> None:
    """Spread aggregate volume across time slots within a window."""
    if volume_usd <= 0 or slots <= 0:
        return

    total_txns = buys + sells
    buy_ratio = buys / total_txns if total_txns > 0 else 0.5
    slot_volume = volume_usd / slots

    for slot in range(slots):
        fraction = (slot + 0.5) / slots
        ts = datetime.utcnow() - end_offset - window * (1 - fraction)
        if ts > datetime.utcnow():
            ts = datetime.utcnow()

        if buys > 0:
            trades.append(NormalizedTrade(
                chain=chain,
                token_address=token_address,
                wallet="aggregate",
                side="BUY",
                amount=0,
                usd_value=round(slot_volume * buy_ratio, 2),
                timestamp=ts,
                dex=dex,
                tx_hash=f"dexscreener:buy:{window_id}:{slot}",
                price_usd=price,
                raw_source="dexscreener",
                metadata={"synthetic": True, "window_slots": slots},
            ))

        if sells > 0:
            trades.append(NormalizedTrade(
                chain=chain,
                token_address=token_address,
                wallet="aggregate",
                side="SELL",
                amount=0,
                usd_value=round(slot_volume * (1 - buy_ratio), 2),
                timestamp=ts,
                dex=dex,
                tx_hash=f"dexscreener:sell:{window_id}:{slot}",
                price_usd=price,
                raw_source="dexscreener",
                metadata={"synthetic": True, "window_slots": slots},
            ))


class DexScreenerOnchainCollector(BaseCollector):
    """Fallback when Dune unavailable — uses pair volume as aggregate flow."""

    source_name = "dexscreener_onchain"

    async def fetch_trades(
        self,
        chain: str,
        token_address: str,
        *,
        since: Optional[datetime] = None,
        cursor: str = "",
        limit: int = 100,
    ) -> tuple[list[NormalizedTrade], str]:
        if cursor:
            return [], ""

        chain = normalize_chain(chain)
        token_address = normalize_address(chain, token_address)
        base_url = settings.DEXSCREENER_API_URL.rstrip("/")

        resp = await api_request(
            "GET",
            f"{base_url}/latest/dex/tokens/{token_address}",
            source="dexscreener_onchain",
            cache_key=f"dexscreener:onchain:{token_address}",
            cache_ttl=120,
            min_interval_ms=300,
        )

        if not isinstance(resp, dict):
            return [], ""

        pairs = resp.get("pairs") or []
        chain_pairs = [
            p for p in pairs
            if normalize_chain(str(p.get("chainId", ""))) == chain
        ]
        if not chain_pairs:
            chain_pairs = pairs

        if not chain_pairs:
            return [], ""

        best = max(
            chain_pairs,
            key=lambda p: float((p.get("volume") or {}).get("h24") or 0),
        )
        price = float(best.get("priceUsd") or 0)
        dex = str(best.get("dexId") or "")

        m5_v = _pair_volume(best, "m5")
        h1_v = max(_pair_volume(best, "h1") - m5_v, 0)
        h6_v = max(_pair_volume(best, "h6") - _pair_volume(best, "h1"), 0)
        h24_v = max(_pair_volume(best, "h24") - _pair_volume(best, "h6"), 0)

        m5_b, m5_s = _pair_txns(best, "m5")
        h1_b, h1_s = _pair_txns(best, "h1")
        h6_b, h6_s = _pair_txns(best, "h6")
        h24_b, h24_s = _pair_txns(best, "h24")

        trades: list[NormalizedTrade] = []

        # Distribute volume across recent windows so heatmaps span hours/days, not one timestamp
        _append_distributed_trades(
            trades, chain=chain, token_address=token_address, dex=dex, price=price,
            volume_usd=m5_v, buys=m5_b, sells=m5_s,
            end_offset=timedelta(minutes=0), window=timedelta(minutes=5), slots=1,
            window_id="m5",
        )
        _append_distributed_trades(
            trades, chain=chain, token_address=token_address, dex=dex, price=price,
            volume_usd=h1_v, buys=max(h1_b - m5_b, 0), sells=max(h1_s - m5_s, 0),
            end_offset=timedelta(minutes=5), window=timedelta(hours=1), slots=4,
            window_id="h1",
        )
        _append_distributed_trades(
            trades, chain=chain, token_address=token_address, dex=dex, price=price,
            volume_usd=h6_v, buys=max(h6_b - h1_b, 0), sells=max(h6_s - h1_s, 0),
            end_offset=timedelta(hours=1), window=timedelta(hours=5), slots=5,
            window_id="h6",
        )
        _append_distributed_trades(
            trades, chain=chain, token_address=token_address, dex=dex, price=price,
            volume_usd=h24_v, buys=max(h24_b - h6_b, 0), sells=max(h24_s - h6_s, 0),
            end_offset=timedelta(hours=6), window=timedelta(hours=18), slots=6,
            window_id="h24",
        )

        # Back-fill earlier days with decaying daily estimates from 24h volume (DexScreener has no daily history)
        daily_base = _pair_volume(best, "h24")
        if daily_base > 0 and h24_b + h24_s > 0:
            for day in range(1, 7):
                decay = 0.82 ** day
                day_vol = daily_base * decay * 0.35
                if day_vol < 1:
                    break
                day_b = max(int(h24_b * decay), 1)
                day_s = max(int(h24_s * decay), 1)
                _append_distributed_trades(
                    trades, chain=chain, token_address=token_address, dex=dex, price=price,
                    volume_usd=day_vol, buys=day_b, sells=day_s,
                    end_offset=timedelta(days=day), window=timedelta(hours=24), slots=4,
                    window_id=f"d{day}",
                )

        if not trades:
            return [], ""

        logger.info(
            "DexScreener fallback: %s/%s distributed %d synthetic points (h24=$%.0f)",
            chain, token_address[:10], len(trades), _pair_volume(best, "h24"),
        )
        return trades[:limit], ""
