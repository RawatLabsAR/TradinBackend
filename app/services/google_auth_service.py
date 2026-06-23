"""Google OAuth ID token verification."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoogleProfile:
    google_id: str
    email: str
    email_verified: bool
    name: str | None = None
    picture: str | None = None


def google_oauth_enabled() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID.strip())


def verify_google_id_token(raw_token: str) -> GoogleProfile:
    if not google_oauth_enabled():
        raise ValueError("Google sign-in is not configured")

    try:
        payload = id_token.verify_oauth2_token(
            raw_token,
            google_requests.Request(),
            settings.GOOGLE_OAUTH_CLIENT_ID.strip(),
        )
    except Exception as exc:
        logger.warning("Google ID token verification failed: %s", exc)
        raise ValueError("Invalid Google token") from exc

    if payload.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Invalid Google token issuer")

    google_id = str(payload.get("sub") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    if not google_id or not email:
        raise ValueError("Google token missing required profile fields")

    return GoogleProfile(
        google_id=google_id,
        email=email,
        email_verified=bool(payload.get("email_verified")),
        name=(payload.get("name") or None),
        picture=(payload.get("picture") or None),
    )
