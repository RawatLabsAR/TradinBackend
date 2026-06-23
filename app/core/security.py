"""Security headers and production startup validation."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

logger = logging.getLogger(__name__)

INSECURE_JWT_SECRETS = {
    "",
    "change-me-in-production-use-long-random-string",
    "change-me-generate-a-long-random-secret",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not settings.DEBUG:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def validate_production_settings() -> None:
    if settings.DEBUG:
        logger.warning("DEBUG=true — OpenAPI docs enabled; do not use in production")
        return

    if settings.JWT_SECRET in INSECURE_JWT_SECRETS or len(settings.JWT_SECRET) < 32:
        raise RuntimeError("Set a strong JWT_SECRET (32+ chars) when DEBUG=false")

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required when DEBUG=false")

    if settings.REGISTRATION_ENABLED and settings.REQUIRE_EMAIL_VERIFICATION:
        if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
            logger.warning(
                "Email verification enabled but SMTP not configured — "
                "verification emails will fail"
            )
