"""Payment provider region resolution."""

from __future__ import annotations

from fastapi import Request

from app.core.plans import PaymentProvider, resolve_payment_provider
from app.models.user import User


def country_from_request(request: Request) -> str | None:
    for header in ("cf-ipcountry", "x-country-code", "x-verified-country"):
        value = request.headers.get(header, "").strip().upper()
        if value and value not in {"XX", "T1"}:
            return value
    return None


def resolve_provider_for_checkout(
    request: Request,
    user: User | None = None,
    country_hint: str | None = None,
) -> PaymentProvider:
    country = (country_hint or "").strip().upper() or None
    if not country and user and getattr(user, "country", None):
        country = user.country.upper()
    if not country:
        country = country_from_request(request)
    return resolve_payment_provider(country)
