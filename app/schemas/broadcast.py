"""
Pydantic schemas for the broadcast system.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── TelegramChannel ───────────────────────────────────────────────────────────

class TelegramChannelCreate(BaseModel):
    chat_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255)
    channel_type: str = Field(default="group")
    description: Optional[str] = None
    send_signals: bool = True
    send_ai: bool = True
    send_news: bool = False
    cooldown_sec: Optional[int] = None


class TelegramChannelUpdate(BaseModel):
    name: Optional[str] = None
    channel_type: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    send_signals: Optional[bool] = None
    send_ai: Optional[bool] = None
    send_news: Optional[bool] = None
    cooldown_sec: Optional[int] = None


class TelegramChannelOut(BaseModel):
    id: int
    name: str
    chat_id: str
    channel_type: str
    description: Optional[str]
    is_active: bool
    send_signals: bool
    send_ai: bool
    send_news: bool
    cooldown_sec: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── BroadcastTemplate ─────────────────────────────────────────────────────────

class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    category: str = Field(default="custom")
    variables: list[str] = Field(default_factory=list)
    parse_mode: str = Field(default="Markdown")


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    variables: Optional[list[str]] = None
    parse_mode: Optional[str] = None
    is_active: Optional[bool] = None


class TemplateOut(BaseModel):
    id: int
    name: str
    category: str
    content: str
    variables: list[str]
    parse_mode: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── BroadcastMessage ──────────────────────────────────────────────────────────

class BroadcastSendRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4096)
    title: Optional[str] = None
    parse_mode: str = Field(default="Markdown")
    channel_ids: Optional[list[int]] = None
    template_id: Optional[int] = None
    template_variables: Optional[dict[str, Any]] = None


class BroadcastScheduleRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4096)
    title: Optional[str] = None
    parse_mode: str = Field(default="Markdown")
    channel_ids: Optional[list[int]] = None
    scheduled_at: datetime
    template_id: Optional[int] = None
    template_variables: Optional[dict[str, Any]] = None


class BroadcastLogOut(BaseModel):
    id: int
    channel_id: int
    status: str
    telegram_msg_id: Optional[int]
    attempt_count: int
    error_message: Optional[str]
    sent_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class BroadcastMessageOut(BaseModel):
    id: int
    title: Optional[str]
    content: str
    parse_mode: str
    message_type: str
    status: str
    template_id: Optional[int]
    target_channel_ids: Optional[list[int]]
    attempt_count: int
    max_attempts: int
    last_error: Optional[str]
    scheduled_at: Optional[datetime]
    sent_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SignalBroadcastRequest(BaseModel):
    symbol: str
    signal_type: str   # BUY | SELL | EXIT
    strategy: str
    timeframe: str
    price: Optional[float] = None
    reason: Optional[str] = None
    sentiment: Optional[str] = None
    ai_commentary: Optional[str] = None


class PaginatedBroadcastHistory(BaseModel):
    items: list[BroadcastMessageOut]
    total: int
    page: int
    page_size: int
    pages: int


class TemplateRenderRequest(BaseModel):
    content: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


class TemplateRenderResponse(BaseModel):
    rendered: str


class SignalBroadcastResponse(BaseModel):
    ok: bool
    message_id: Optional[int] = None
    status: Optional[str] = None
    detail: Optional[str] = None


class TelegramValidateChatRequest(BaseModel):
    chat_id: str = Field(..., min_length=1)


class TelegramSendTestRequest(BaseModel):
    chat_id: str = Field(..., min_length=1)
    text: str = "🤖 Test message from Tradin broadcast system."


class TelegramBotTestResponse(BaseModel):
    ok: bool
    bot_username: Optional[str] = None
    bot_name: Optional[str] = None
    bot_id: Optional[int] = None
    error: Optional[str] = None


class TelegramSendTestResponse(BaseModel):
    ok: bool
    message_id: Optional[int] = None
    error: Optional[str] = None


class DiscoveredChat(BaseModel):
    chat_id: str
    title: str
    type: str
    username: Optional[str] = None
    already_added: bool = False


class DiscoverChatsResponse(BaseModel):
    ok: bool
    chats: list[DiscoveredChat] = Field(default_factory=list)
    total: int = 0
    hint: Optional[str] = None
    error: Optional[str] = None
