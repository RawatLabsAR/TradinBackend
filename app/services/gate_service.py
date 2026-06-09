"""
Gate.io Spot REST API service.

Public endpoints (no API key required):
  GET /spot/tickers
  GET /spot/tickers?currency_pair={pair}
  GET /spot/currency_pairs/{currency_pair}
  GET /spot/candlesticks
  GET /spot/trades

All responses are normalised to match the Coinbase field shapes expected by
market_service.py so no changes are needed upstream.
"""

import asyncio
import logging
import datetime
from typing import Any, Optional

import aiohttp

from app.core.config import settings
from app.schemas.candle import GATE_GRANULARITY_MAP, TIMEFRAME_CONFIG

logger = logging.getLogger(__name__)

_session: Optional[aiohttp.ClientSession] = None

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        _session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    return _session


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _get(
    path: str,
    params: Optional[dict] = None,
    retries: int = 3,
    backoff: float = 1.0,
) -> Any:
    url = f"{settings.GATE_API_BASE_URL}{path}"
    session = _get_session()

    for attempt in range(retries):
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    wait = backoff * (2 ** attempt)
                    logger.warning("Rate limited by Gate.io, waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error("Gate.io API error %d: %s", resp.status, text)
                    resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as exc:
            if attempt == retries - 1:
                raise
            wait = backoff * (2 ** attempt)
            logger.warning("Gate.io request failed (attempt %d): %s", attempt + 1, exc)
            await asyncio.sleep(wait)

    raise RuntimeError(f"Gate.io API request failed after {retries} attempts: {path}")


# ---------------------------------------------------------------------------
# ID conversion helpers
# ---------------------------------------------------------------------------

def _to_gate_pair(product_id: str) -> str:
    """'BTC-USD'  →  'BTC_USDT'  (spot pairs only)."""
    market, contract, _ = _parse_product_id(product_id)
    if market != "spot":
        raise ValueError(f"Not a spot product: {product_id}")
    return contract


def _to_product_id(gate_pair: str) -> str:
    """'BTC_USDT'  →  'BTC-USD'  (internal canonical spot ID)."""
    parts = gate_pair.split("_")
    base = parts[0]
    return f"{base}-USD"


def _parse_product_id(product_id: str) -> tuple[str, str, str]:
    """Return (market, contract, product_type) for spot/swap/futures IDs."""
    upper = product_id.upper()
    if upper.endswith("-SWAP"):
        base = upper[: upper.rindex("-USD-SWAP")]
        return "futures", f"{base}_USDT", "SWAP"

    parts = upper.split("-")
    if len(parts) == 3 and len(parts[2]) == 8 and parts[2].isdigit():
        return "delivery", f"{parts[0]}_USDT_{parts[2]}", "FUTURES"

    return "spot", f"{parts[0]}_USDT", "SPOT"


def _contract_to_product_id(contract: str, product_type: str) -> str:
    parts = contract.split("_")
    base = parts[0]
    if product_type == "SWAP":
        return f"{base}-USD-SWAP"
    if product_type == "FUTURES" and len(parts) >= 3:
        return f"{base}-USD-{parts[-1]}"
    return f"{base}-USD"


def _is_perpetual_contract(contract: str) -> bool:
    parts = contract.split("_")
    return len(parts) == 2 and parts[1] == "USDT"


def _is_delivery_contract(contract: str) -> bool:
    parts = contract.split("_")
    return len(parts) == 3 and parts[1] == "USDT" and parts[2].isdigit()


def _product_volume(product: dict) -> float:
    try:
        return float(product.get("approximate_quote_24h_volume") or 0)
    except ValueError:
        return 0.0


def _paginate_products(products: list[dict], limit: int, offset: int) -> list[dict]:
    if limit > 0:
        return products[offset: offset + limit]
    if offset > 0:
        return products[offset:]
    return products


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm_ticker(ticker: dict) -> dict:
    """Gate ticker dict → Coinbase-shaped product dict."""
    pair = ticker.get("currency_pair", "")
    base = pair.split("_")[0] if "_" in pair else pair
    product_id = _to_product_id(pair)

    change_pct = ticker.get("change_percentage", "0") or "0"

    return {
        "product_id": product_id,
        "price": ticker.get("last", "0"),
        "price_percentage_change_24h": change_pct,
        "volume_24h": ticker.get("base_volume", "0"),
        "volume_percentage_change_24h": "0",
        "base_name": base,
        "quote_name": "USD",
        "quote_currency_id": "USD",
        "base_currency_id": base,
        "display_name": f"{base}/USD",
        "base_display_symbol": base,
        "quote_display_symbol": "USD",
        "mid_market_price": ticker.get("last", "0"),
        "approximate_quote_24h_volume": ticker.get("quote_volume", "0"),
        "is_disabled": False,
        "trading_disabled": False,
        "status": "online",
        "new": False,
        "cancel_only": False,
        "limit_only": False,
        "post_only": False,
        "auction_mode": False,
        "product_type": "SPOT",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "base_min_size": "0.00000001",
        "base_max_size": "1000000",
        # Extra bid/ask from ticker when available
        "best_bid": ticker.get("highest_bid", ""),
        "best_ask": ticker.get("lowest_ask", ""),
    }


def _norm_derivative_ticker(ticker: dict, product_type: str) -> dict:
    """Gate perpetual/delivery ticker → Coinbase-shaped product dict."""
    contract = ticker.get("contract", "")
    parts = contract.split("_")
    base = parts[0]
    product_id = _contract_to_product_id(contract, product_type)
    change_pct = ticker.get("change_percentage", "0") or "0"
    quote_volume = (
        ticker.get("volume_24h_quote")
        or ticker.get("volume_24h_settle")
        or "0"
    )

    if product_type == "FUTURES":
        expiry = parts[-1] if len(parts) >= 3 else ""
        display_name = f"{base}/USD {expiry}"
    else:
        display_name = f"{base}/USD Perp"

    return {
        "product_id": product_id,
        "price": ticker.get("last", "0"),
        "price_percentage_change_24h": change_pct,
        "volume_24h": str(ticker.get("volume_24h", "0")),
        "volume_percentage_change_24h": "0",
        "base_name": base,
        "quote_name": "USD",
        "quote_currency_id": "USD",
        "base_currency_id": base,
        "display_name": display_name,
        "base_display_symbol": base,
        "quote_display_symbol": "USD",
        "mid_market_price": ticker.get("mark_price", ticker.get("last", "0")),
        "approximate_quote_24h_volume": str(quote_volume),
        "is_disabled": False,
        "trading_disabled": False,
        "status": "online",
        "new": False,
        "cancel_only": False,
        "limit_only": False,
        "post_only": False,
        "auction_mode": False,
        "product_type": product_type,
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "base_min_size": "0.00000001",
        "base_max_size": "1000000",
        "best_bid": ticker.get("highest_bid", ""),
        "best_ask": ticker.get("lowest_ask", ""),
    }


def _enrich_with_pair_info(product: dict, pair_info: dict) -> dict:
    """Overlay currency-pair detail fields (min/max sizes, precision)."""
    product["base_increment"] = pair_info.get("min_base_amount", "0.00000001") or "0.00000001"
    product["quote_increment"] = pair_info.get("min_quote_amount", "0.01") or "0.01"
    product["base_min_size"] = pair_info.get("min_base_amount", "0.00000001") or "0.00000001"
    product["base_max_size"] = pair_info.get("max_base_amount", "1000000") or "1000000"
    if pair_info.get("trade_status") == "untradable":
        product["trading_disabled"] = True
        product["status"] = "offline"
    return product


def _norm_candle(raw: list) -> dict:
    """Gate candlestick array → Coinbase candle dict.

    Gate format: [timestamp, volume, close, high, low, open, is_confirmed?]
    """
    return {
        "start": str(raw[0]),
        "volume": str(raw[1]),
        "close": str(raw[2]),
        "high": str(raw[3]),
        "low": str(raw[4]),
        "open": str(raw[5]),
    }


def _norm_derivative_candle(raw: dict) -> dict:
    """Gate futures/delivery candlestick dict → Coinbase candle dict."""
    return {
        "start": str(raw.get("t", "")),
        "volume": str(raw.get("v", "0")),
        "close": str(raw.get("c", "0")),
        "high": str(raw.get("h", "0")),
        "low": str(raw.get("l", "0")),
        "open": str(raw.get("o", "0")),
    }


def _norm_derivative_trade(raw: dict, product_id: str) -> dict:
    """Gate futures/delivery trade dict → Coinbase trade dict."""
    size = raw.get("size", 0)
    try:
        side = "SELL" if float(size) < 0 else "BUY"
    except (TypeError, ValueError):
        side = "BUY"
    return {
        "trade_id": str(raw.get("id", "")),
        "product_id": product_id,
        "price": raw.get("price", "0"),
        "size": str(abs(float(size))) if size not in ("", None) else "0",
        "side": side,
        "time": _epoch_to_iso(raw.get("create_time_ms", raw.get("create_time", ""))),
    }


def _epoch_to_iso(ts) -> str:
    """Convert a Gate timestamp (seconds or milliseconds, int/float/str) to ISO 8601."""
    try:
        t = float(ts)
        if t > 1e11:   # milliseconds
            t /= 1000
        return datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).isoformat()
    except (ValueError, TypeError):
        return ""


def _norm_trade(raw: dict, product_id: str) -> dict:
    """Gate trade dict → Coinbase trade dict."""
    return {
        "trade_id": str(raw.get("id", "")),
        "product_id": product_id,
        "price": raw.get("price", "0"),
        "size": raw.get("amount", "0"),
        "side": raw.get("side", "buy").upper(),
        "time": _epoch_to_iso(raw.get("create_time_ms", raw.get("create_time", ""))),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _fetch_spot_products(
    limit: int,
    offset: int,
    product_ids: Optional[list[str]] = None,
) -> list[dict]:
    tickers: list[dict] = await _get("/spot/tickers")
    tickers = [t for t in tickers if t.get("currency_pair", "").endswith("_USDT")]

    if product_ids:
        wanted = {_parse_product_id(pid)[1] for pid in product_ids}
        tickers = [t for t in tickers if t["currency_pair"] in wanted]

    tickers.sort(
        key=lambda t: float(t.get("quote_volume") or 0),
        reverse=True,
    )
    tickers = _paginate_products(tickers, limit, offset)
    return [_norm_ticker(t) for t in tickers]


async def _fetch_swap_products(
    limit: int,
    offset: int,
    product_ids: Optional[list[str]] = None,
) -> list[dict]:
    tickers: list[dict] = await _get("/futures/usdt/tickers")
    tickers = [t for t in tickers if _is_perpetual_contract(t.get("contract", ""))]

    if product_ids:
        wanted = {_parse_product_id(pid)[1] for pid in product_ids if _parse_product_id(pid)[2] == "SWAP"}
        tickers = [t for t in tickers if t.get("contract") in wanted]

    tickers.sort(
        key=lambda t: float(t.get("volume_24h_quote") or t.get("volume_24h_settle") or 0),
        reverse=True,
    )
    tickers = _paginate_products(tickers, limit, offset)
    return [_norm_derivative_ticker(t, "SWAP") for t in tickers]


async def _fetch_futures_products(
    limit: int,
    offset: int,
    product_ids: Optional[list[str]] = None,
) -> list[dict]:
    tickers: list[dict] = await _get("/delivery/usdt/tickers")
    tickers = [t for t in tickers if _is_delivery_contract(t.get("contract", ""))]

    if product_ids:
        wanted = {_parse_product_id(pid)[1] for pid in product_ids if _parse_product_id(pid)[2] == "FUTURES"}
        tickers = [t for t in tickers if t.get("contract") in wanted]

    tickers.sort(
        key=lambda t: float(t.get("volume_24h_quote") or t.get("volume_24h_settle") or 0),
        reverse=True,
    )
    tickers = _paginate_products(tickers, limit, offset)
    return [_norm_derivative_ticker(t, "FUTURES") for t in tickers]


async def get_products(
    limit: int = 250,
    offset: int = 0,
    product_type: str = "SPOT",
    product_ids: Optional[list[str]] = None,
) -> dict:
    """List products — normalised to Coinbase product shape.

    Supported product_type values: SPOT, SWAP, FUTURES, ALL.
    """
    ptype = product_type.upper()

    if ptype == "ALL":
        spot, swap, futures = await asyncio.gather(
            _fetch_spot_products(0, 0, product_ids),
            _fetch_swap_products(0, 0, product_ids),
            _fetch_futures_products(0, 0, product_ids),
        )
        products = spot + swap + futures
        products.sort(key=_product_volume, reverse=True)
        return {"products": _paginate_products(products, limit, offset)}

    if ptype == "SWAP":
        products = await _fetch_swap_products(limit, offset, product_ids)
    elif ptype == "FUTURES":
        products = await _fetch_futures_products(limit, offset, product_ids)
    else:
        products = await _fetch_spot_products(limit, offset, product_ids)

    return {"products": products}


async def get_product(product_id: str) -> dict:
    """Get single product detail for spot, swap, or delivery futures."""
    market, contract, ptype = _parse_product_id(product_id)

    if market == "futures":
        ticker_data = await _get("/futures/usdt/tickers", params={"contract": contract})
        ticker = {}
        if isinstance(ticker_data, list) and ticker_data:
            ticker = ticker_data[0]
        elif isinstance(ticker_data, dict):
            ticker = ticker_data
        return _norm_derivative_ticker(ticker if ticker else {"contract": contract}, "SWAP")

    if market == "delivery":
        ticker_data = await _get("/delivery/usdt/tickers", params={"contract": contract})
        ticker = {}
        if isinstance(ticker_data, list) and ticker_data:
            ticker = ticker_data[0]
        elif isinstance(ticker_data, dict):
            ticker = ticker_data
        return _norm_derivative_ticker(ticker if ticker else {"contract": contract}, "FUTURES")

    ticker_data, pair_info = await asyncio.gather(
        _get("/spot/tickers", params={"currency_pair": contract}),
        _get(f"/spot/currency_pairs/{contract}"),
        return_exceptions=True,
    )

    ticker = {}
    if isinstance(ticker_data, list) and ticker_data:
        ticker = ticker_data[0]
    elif isinstance(ticker_data, dict):
        ticker = ticker_data

    product = _norm_ticker(ticker if ticker else {"currency_pair": contract})

    if isinstance(pair_info, dict):
        product = _enrich_with_pair_info(product, pair_info)

    return product


async def get_candles(
    product_id: str,
    start: int,
    end: int,
    granularity: str,
    gate_interval: str | None = None,
) -> dict:
    """Fetch OHLCV candles for spot, swap, or delivery futures."""
    gate_interval = gate_interval or _coinbase_granularity_to_gate(granularity)
    market, contract, _ = _parse_product_id(product_id)

    if market == "futures":
        raw: list = await _get(
            "/futures/usdt/candlesticks",
            params={
                "contract": contract,
                "interval": gate_interval,
                "from": str(start),
                "to": str(end),
            },
        )
        if not isinstance(raw, list):
            return {"candles": []}
        candles = [_norm_derivative_candle(c) for c in reversed(raw)]
        return {"candles": candles}

    if market == "delivery":
        raw = await _get(
            "/delivery/usdt/candlesticks",
            params={
                "contract": contract,
                "interval": gate_interval,
                "from": str(start),
                "to": str(end),
            },
        )
        if not isinstance(raw, list):
            return {"candles": []}
        candles = [_norm_derivative_candle(c) for c in reversed(raw)]
        return {"candles": candles}

    raw = await _get(
        "/spot/candlesticks",
        params={
            "currency_pair": contract,
            "interval": gate_interval,
            "from": str(start),
            "to": str(end),
            "limit": 1000,
        },
    )

    if not isinstance(raw, list):
        return {"candles": []}

    candles = [_norm_candle(c) for c in reversed(raw)]
    return {"candles": candles}


async def get_market_trades(product_id: str, limit: int = 25) -> dict:
    """Fetch recent trades + best bid/ask for spot, swap, or delivery futures."""
    market, contract, _ = _parse_product_id(product_id)

    if market == "futures":
        trades_raw, ticker_data = await asyncio.gather(
            _get("/futures/usdt/trades", params={"contract": contract, "limit": limit}),
            _get("/futures/usdt/tickers", params={"contract": contract}),
            return_exceptions=True,
        )
        trades = []
        if isinstance(trades_raw, list):
            trades = [_norm_derivative_trade(t, product_id) for t in trades_raw]
        best_bid = best_ask = ""
        if isinstance(ticker_data, list) and ticker_data:
            t = ticker_data[0]
            best_bid = t.get("highest_bid", "")
            best_ask = t.get("lowest_ask", "")
        return {
            "trades": trades,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "best_bid_size": "",
            "best_ask_size": "",
        }

    if market == "delivery":
        trades_raw, ticker_data = await asyncio.gather(
            _get("/delivery/usdt/trades", params={"contract": contract, "limit": limit}),
            _get("/delivery/usdt/tickers", params={"contract": contract}),
            return_exceptions=True,
        )
        trades = []
        if isinstance(trades_raw, list):
            trades = [_norm_derivative_trade(t, product_id) for t in trades_raw]
        best_bid = best_ask = ""
        if isinstance(ticker_data, list) and ticker_data:
            t = ticker_data[0]
            best_bid = t.get("highest_bid", "")
            best_ask = t.get("lowest_ask", "")
        return {
            "trades": trades,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "best_bid_size": "",
            "best_ask_size": "",
        }

    trades_raw, ticker_data = await asyncio.gather(
        _get("/spot/trades", params={"currency_pair": contract, "limit": limit}),
        _get("/spot/tickers", params={"currency_pair": contract}),
        return_exceptions=True,
    )

    trades = []
    if isinstance(trades_raw, list):
        trades = [_norm_trade(t, product_id) for t in trades_raw]

    best_bid = best_ask = best_bid_size = best_ask_size = ""
    if isinstance(ticker_data, list) and ticker_data:
        t = ticker_data[0]
        best_bid = t.get("highest_bid", "")
        best_ask = t.get("lowest_ask", "")

    return {
        "trades": trades,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_size": best_bid_size,
        "best_ask_size": best_ask_size,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coinbase_granularity_to_gate(granularity: str) -> str:
    """Map a Coinbase granularity constant to a Gate.io interval string."""
    _map = {
        "ONE_MINUTE": "1m",
        "FIVE_MINUTE": "5m",
        "FIFTEEN_MINUTE": "15m",
        "THIRTY_MINUTE": "30m",
        "ONE_HOUR": "1h",
        "TWO_HOUR": "2h",
        "FOUR_HOUR": "4h",
        "SIX_HOUR": "6h",
        "ONE_DAY": "1d",
        "ONE_WEEK": "1w",
        "ONE_MONTH": "1M",
    }
    return _map.get(granularity, "1h")
