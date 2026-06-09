"""
Template engine for the broadcast system.

Handles:
  - CRUD operations on BroadcastTemplate DB rows
  - Variable substitution using {{key}} syntax
  - Seeding default templates on first run
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broadcast import BroadcastTemplate
from app.integrations.telegram.message_formatter import render_template
from app.broadcast.templates.default_templates import DEFAULT_TEMPLATES

logger = logging.getLogger(__name__)


class TemplateEngine:

    async def seed_defaults(self, db: AsyncSession) -> None:
        """Insert default templates if they don't already exist."""
        for tpl in DEFAULT_TEMPLATES:
            exists = await db.execute(
                select(BroadcastTemplate).where(BroadcastTemplate.name == tpl["name"])
            )
            if exists.scalar_one_or_none() is None:
                db.add(BroadcastTemplate(**tpl))
        await db.flush()
        logger.info("Default broadcast templates seeded")

    async def list_templates(
        self, db: AsyncSession, category: Optional[str] = None, active_only: bool = True
    ) -> list[BroadcastTemplate]:
        stmt = select(BroadcastTemplate)
        if active_only:
            stmt = stmt.where(BroadcastTemplate.is_active == True)  # noqa: E712
        if category:
            stmt = stmt.where(BroadcastTemplate.category == category)
        stmt = stmt.order_by(BroadcastTemplate.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_template(
        self, db: AsyncSession, template_id: int
    ) -> Optional[BroadcastTemplate]:
        result = await db.execute(
            select(BroadcastTemplate).where(BroadcastTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def create_template(
        self,
        db: AsyncSession,
        name: str,
        content: str,
        category: str = "custom",
        variables: Optional[list[str]] = None,
        parse_mode: str = "Markdown",
    ) -> BroadcastTemplate:
        tpl = BroadcastTemplate(
            name=name,
            content=content,
            category=category,
            variables=variables or [],
            parse_mode=parse_mode,
        )
        db.add(tpl)
        await db.flush()
        logger.info("Created broadcast template '%s'", name)
        return tpl

    async def update_template(
        self, db: AsyncSession, template_id: int, **fields: Any
    ) -> Optional[BroadcastTemplate]:
        tpl = await self.get_template(db, template_id)
        if not tpl:
            return None
        for k, v in fields.items():
            if hasattr(tpl, k):
                setattr(tpl, k, v)
        await db.flush()
        return tpl

    async def delete_template(self, db: AsyncSession, template_id: int) -> bool:
        tpl = await self.get_template(db, template_id)
        if not tpl:
            return False
        await db.delete(tpl)
        await db.flush()
        return True

    def render(self, template_content: str, variables: dict[str, Any]) -> str:
        return render_template(template_content, variables)


template_engine = TemplateEngine()
