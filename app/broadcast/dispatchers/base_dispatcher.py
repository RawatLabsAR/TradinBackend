"""
Abstract base broadcaster.

Future broadcasters (Discord, Slack, WhatsApp, Email) implement this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseBroadcaster(ABC):
    """Transport-agnostic broadcaster contract."""

    @abstractmethod
    async def send(
        self,
        destination: str,
        content: str,
        parse_mode: str = "Markdown",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Send *content* to *destination*.

        Returns a dict with at minimum:
          { "ok": bool, "message_id": int | None, "error": str | None }
        """

    @abstractmethod
    async def start(self) -> None:
        """Initialise any connections / sessions."""

    @abstractmethod
    async def stop(self) -> None:
        """Clean up connections / sessions."""
