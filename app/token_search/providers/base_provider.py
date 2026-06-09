"""Abstract token search provider."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.token_search.types import NormalizedToken


class BaseTokenProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedToken]:
        ...

    async def get_token(
        self,
        chain: str,
        contract_address: str,
    ) -> NormalizedToken | None:
        return None
