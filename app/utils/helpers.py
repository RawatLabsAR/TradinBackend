"""Miscellaneous helpers."""

import re
from decimal import Decimal, InvalidOperation


def safe_float(value: str | None, default: float = 0.0) -> float:
    """Parse a string to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_decimal(value: str | None, default: Decimal = Decimal("0")) -> Decimal:
    """Parse a string to Decimal, returning default on failure."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return default


def extract_base_currency(product_id: str) -> str:
    """Extract base currency from product_id (e.g. 'BTC-USD' → 'BTC')."""
    parts = product_id.split("-")
    return parts[0] if parts else product_id


def extract_quote_currency(product_id: str) -> str:
    """Extract quote currency from product_id (e.g. 'BTC-USD' → 'USD')."""
    parts = product_id.split("-")
    return parts[1] if len(parts) > 1 else "USD"


def sanitize_product_id(product_id: str) -> str:
    """Ensure product_id is safe for use in DB queries."""
    return re.sub(r"[^A-Z0-9\-]", "", product_id.upper())[:20]
