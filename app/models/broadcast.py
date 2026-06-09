"""
SQLAlchemy models for the Telegram broadcasting system.

Tables:
  telegram_channels        – registered Telegram chats/channels/groups
  broadcast_templates      – reusable message templates with variable substitution
  broadcast_messages       – every broadcast attempt (manual + automated)
  broadcast_logs           – per-channel delivery log for each message
  scheduled_broadcasts     – future-dated messages waiting to be sent
  signal_broadcast_history – links strategy signals → broadcast messages
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float,
    ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────── telegram_channels ───────────────────────────────

class TelegramChannel(Base):
    __tablename__ = "telegram_channels"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    name          = Column(String(255), nullable=False)
    chat_id       = Column(String(64), nullable=False, unique=True)
    channel_type  = Column(String(32), nullable=False, default="group")
    # channel_type: "group" | "channel" | "private" | "supergroup"
    description   = Column(Text, nullable=True)
    is_active     = Column(Boolean, nullable=False, default=True)

    # Auto-broadcast toggles
    send_signals  = Column(Boolean, nullable=False, default=True)
    send_ai       = Column(Boolean, nullable=False, default=True)
    send_news     = Column(Boolean, nullable=False, default=False)

    # Cooldown per channel (seconds) — overrides global setting
    cooldown_sec  = Column(Integer, nullable=True)

    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at    = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    broadcast_logs = relationship("BroadcastLog", back_populates="channel",
                                  cascade="all, delete-orphan", lazy="select")

    __table_args__ = (
        Index("ix_telegram_channels_is_active", "is_active"),
        Index("ix_telegram_channels_chat_id", "chat_id"),
    )


# ─────────────────────────── broadcast_templates ─────────────────────────────

class BroadcastTemplate(Base):
    __tablename__ = "broadcast_templates"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(255), nullable=False, unique=True)
    category    = Column(String(64), nullable=False, default="custom")
    # category: "signal" | "ai_insight" | "news" | "custom" | "alert"
    content     = Column(Text, nullable=False)
    variables   = Column(JSON, nullable=True, default=list)
    # list of variable names used in the template, e.g. ["symbol", "price"]
    parse_mode  = Column(String(16), nullable=False, default="Markdown")
    is_active   = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at  = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_broadcast_templates_category", "category"),
        Index("ix_broadcast_templates_is_active", "is_active"),
    )


# ─────────────────────────── broadcast_messages ──────────────────────────────

class BroadcastMessage(Base):
    __tablename__ = "broadcast_messages"

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    title        = Column(String(512), nullable=True)
    content      = Column(Text, nullable=False)
    parse_mode   = Column(String(16), nullable=False, default="Markdown")
    message_type = Column(String(32), nullable=False, default="manual")
    # message_type: "manual" | "signal" | "ai_insight" | "news" | "scheduled"
    status       = Column(String(16), nullable=False, default="pending")
    # status: "pending" | "queued" | "sent" | "partial" | "failed" | "cancelled"

    # Optional link back to a template
    template_id  = Column(Integer, ForeignKey("broadcast_templates.id", ondelete="SET NULL"),
                          nullable=True)
    template_variables = Column(JSON, nullable=True, default=dict)

    # Target channels — list of channel IDs (empty = all active channels)
    target_channel_ids = Column(JSON, nullable=True, default=list)

    # Deduplication hash (prevents sending same message twice)
    dedup_hash   = Column(String(64), nullable=True)

    # Retry tracking
    attempt_count  = Column(Integer, nullable=False, default=0)
    max_attempts   = Column(Integer, nullable=False, default=3)
    last_error     = Column(Text, nullable=True)

    # Scheduling
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    sent_at      = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at   = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    template   = relationship("BroadcastTemplate", lazy="select")
    logs       = relationship("BroadcastLog", back_populates="message",
                              cascade="all, delete-orphan", lazy="select")
    signal_ref = relationship("SignalBroadcastHistory", back_populates="message",
                               uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_broadcast_messages_status", "status"),
        Index("ix_broadcast_messages_message_type", "message_type"),
        Index("ix_broadcast_messages_created_at", "created_at"),
        Index("ix_broadcast_messages_scheduled_at", "scheduled_at"),
        Index("ix_broadcast_messages_dedup_hash", "dedup_hash"),
    )


# ─────────────────────────── broadcast_logs ──────────────────────────────────

class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id    = Column(BigInteger, ForeignKey("broadcast_messages.id", ondelete="CASCADE"),
                           nullable=False)
    channel_id    = Column(Integer, ForeignKey("telegram_channels.id", ondelete="CASCADE"),
                           nullable=False)

    status        = Column(String(16), nullable=False, default="pending")
    # status: "pending" | "sent" | "failed" | "skipped"

    telegram_msg_id = Column(BigInteger, nullable=True)
    attempt_count   = Column(Integer, nullable=False, default=0)
    error_message   = Column(Text, nullable=True)
    sent_at         = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at      = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    message  = relationship("BroadcastMessage", back_populates="logs")
    channel  = relationship("TelegramChannel", back_populates="broadcast_logs")

    __table_args__ = (
        Index("ix_broadcast_logs_message_id", "message_id"),
        Index("ix_broadcast_logs_channel_id", "channel_id"),
        Index("ix_broadcast_logs_status", "status"),
        Index("ix_broadcast_logs_sent_at", "sent_at"),
    )


# ─────────────────────────── scheduled_broadcasts ────────────────────────────

class ScheduledBroadcast(Base):
    __tablename__ = "scheduled_broadcasts"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    message_id    = Column(BigInteger, ForeignKey("broadcast_messages.id", ondelete="CASCADE"),
                           nullable=False, unique=True)
    scheduled_at  = Column(DateTime(timezone=True), nullable=False)
    repeat_type   = Column(String(16), nullable=False, default="once")
    # repeat_type: "once" | "daily" | "weekly"
    repeat_cron   = Column(String(64), nullable=True)
    status        = Column(String(16), nullable=False, default="pending")
    # status: "pending" | "sent" | "cancelled" | "failed"
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at    = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    message = relationship("BroadcastMessage", lazy="select")

    __table_args__ = (
        Index("ix_scheduled_broadcasts_scheduled_at", "scheduled_at"),
        Index("ix_scheduled_broadcasts_status", "status"),
    )


# ─────────────────────────── signal_broadcast_history ────────────────────────

class SignalBroadcastHistory(Base):
    __tablename__ = "signal_broadcast_history"

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id   = Column(BigInteger, ForeignKey("broadcast_messages.id", ondelete="CASCADE"),
                          nullable=False, unique=True)
    symbol       = Column(String(32), nullable=False)
    signal_type  = Column(String(16), nullable=False)   # BUY | SELL | EXIT
    strategy     = Column(String(255), nullable=True)
    timeframe    = Column(String(8), nullable=True)
    price        = Column(Float, nullable=True)
    sentiment    = Column(String(32), nullable=True)
    reason       = Column(Text, nullable=True)
    ai_commentary = Column(Text, nullable=True)
    extra_data   = Column(JSON, nullable=True, default=dict)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)

    message = relationship("BroadcastMessage", back_populates="signal_ref")

    __table_args__ = (
        Index("ix_signal_broadcast_history_symbol", "symbol"),
        Index("ix_signal_broadcast_history_signal_type", "signal_type"),
        Index("ix_signal_broadcast_history_created_at", "created_at"),
        UniqueConstraint("message_id", name="uq_signal_broadcast_message"),
    )
