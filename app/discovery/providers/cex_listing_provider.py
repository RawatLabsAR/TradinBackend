"""Detect newly listed CEX trading pairs via catalog diff."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.cache import cache
from app.core.config import settings
from app.discovery.providers.base_discovery_provider import BaseDiscoveryProvider
from app.discovery.types import DiscoveryToken
from app.providers.registry import get_market_provider

logger = logging.getLogger(__name__)

CATALOG_CACHE_KEY = "discovery:cex:catalog_ids"
CATALOG_FIRST_SEEN_KEY = "discovery:cex:first_seen"


class CexListingProvider(BaseDiscoveryProvider):
    name = "cex_listings"
    category = "new_cex"

    async def _fetch_all_products(self) -> list[dict]:
        provider = get_market_provider()
        data = await provider.get_products(limit=0, product_type="SPOT")
        return data.get("products") or []

    def _product_to_token(self, product: dict) -> DiscoveryToken:
        product_id = str(product.get("product_id") or product.get("id") or "")
        base = product_id.split("-")[0] if "-" in product_id else product_id
        volume = float(product.get("volume_24h") or product.get("quote_volume") or 0)
        price = float(product.get("price") or product.get("last") or 0)
        change = float(
            product.get("price_percentage_change_24h")
            or product.get("change_percentage")
            or 0
        )

        return DiscoveryToken(
            token_name=base,
            symbol=base.upper(),
            chain="cex",
            contract_address="",
            volume_24h=volume,
            price_usd=price,
            price_change_24h=change,
            verified=True,
            source=settings.DATA_PROVIDER,
            discovery_category=self.category,
            source_type="cex",
            product_id=product_id,
            risk_level="low",
            metadata={"product": product},
        )

    async def fetch(self, *, limit: int = 50) -> list[DiscoveryToken]:
        products = await self._fetch_all_products()
        current_ids = {str(p.get("product_id") or p.get("id") or "") for p in products}
        current_ids.discard("")

        known_ids: set[str] = cache.get(CATALOG_CACHE_KEY) or set()
        first_seen: dict[str, str] = cache.get(CATALOG_FIRST_SEEN_KEY) or {}

        now_iso = datetime.now(timezone.utc).isoformat()
        for pid in current_ids:
            if pid not in first_seen:
                first_seen[pid] = now_iso

        new_ids = current_ids - known_ids if known_ids else set()

        cache.set(CATALOG_CACHE_KEY, current_ids, ttl=86400 * 7)
        cache.set(CATALOG_FIRST_SEEN_KEY, first_seen, ttl=86400 * 7)

        if not known_ids:
            logger.info("CEX catalog baseline stored (%d products)", len(current_ids))
            return []

        product_map = {
            str(p.get("product_id") or p.get("id") or ""): p for p in products
        }

        tokens: list[DiscoveryToken] = []
        for pid in new_ids:
            product = product_map.get(pid)
            if not product:
                continue
            token = self._product_to_token(product)
            seen_at = first_seen.get(pid, now_iso)
            try:
                dt = datetime.fromisoformat(seen_at.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                token.age_hours = max(
                    0.0,
                    (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0,
                )
            except ValueError:
                token.age_hours = 0.0
            tokens.append(token)

        tokens.sort(key=lambda t: t.volume_24h, reverse=True)
        return tokens[:limit]

    async def fetch_all_recent(self, *, max_age_hours: float = 168, limit: int = 50) -> list[DiscoveryToken]:
        """Return CEX products first seen within max_age_hours."""
        products = await self._fetch_all_products()
        current_ids = {str(p.get("product_id") or p.get("id") or "") for p in products}
        current_ids.discard("")

        first_seen: dict[str, str] = cache.get(CATALOG_FIRST_SEEN_KEY) or {}
        now = datetime.now(timezone.utc)

        for pid in current_ids:
            if pid not in first_seen:
                first_seen[pid] = now.isoformat()
        cache.set(CATALOG_FIRST_SEEN_KEY, first_seen, ttl=86400 * 7)
        cache.set(CATALOG_CACHE_KEY, current_ids, ttl=86400 * 7)

        product_map = {
            str(p.get("product_id") or p.get("id") or ""): p for p in products
        }

        tokens: list[DiscoveryToken] = []
        for pid, seen_at in first_seen.items():
            if pid not in current_ids:
                continue
            try:
                dt = datetime.fromisoformat(seen_at.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_hours = (now - dt).total_seconds() / 3600.0
            except ValueError:
                continue
            if age_hours > max_age_hours:
                continue
            product = product_map.get(pid)
            if not product:
                continue
            token = self._product_to_token(product)
            token.age_hours = age_hours
            tokens.append(token)

        tokens.sort(key=lambda t: t.age_hours)
        return tokens[:limit]
