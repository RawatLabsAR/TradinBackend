"""Abstract discovery data provider."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.discovery.types import DiscoveryToken


class BaseDiscoveryProvider(ABC):
    name: str = "base"
    category: str = ""

    @abstractmethod
    async def fetch(self, *, limit: int = 50) -> list[DiscoveryToken]:
        ...
