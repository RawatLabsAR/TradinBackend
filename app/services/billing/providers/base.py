"""Billing provider protocol."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import PlanId
from app.models.user import User


class BillingProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def plan_available(self, plan_id: PlanId) -> bool: ...

    async def create_checkout(self, db: AsyncSession, user: User, plan_id: PlanId) -> str: ...

    async def create_portal(self, db: AsyncSession, user: User) -> str | None: ...

    async def handle_webhook(self, db: AsyncSession, payload: bytes, signature: str) -> None: ...
