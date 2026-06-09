"""
Telegram channel management REST API.

GET    /api/telegram/channels         — list channels
POST   /api/telegram/channels         — add channel
GET    /api/telegram/channels/{id}    — get channel
PUT    /api/telegram/channels/{id}    — update channel
DELETE /api/telegram/channels/{id}    — remove channel
POST   /api/telegram/test             — test bot token
POST   /api/telegram/validate         — validate a chat_id
POST   /api/telegram/send-test        — send a test message
GET    /api/telegram/discover         — discover chats from bot's recent updates
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.integrations.telegram.telegram_service import get_telegram_service
from app.integrations.telegram.channel_manager import ChannelManager
from app.schemas.broadcast import (
    TelegramChannelCreate,
    TelegramChannelUpdate,
    TelegramChannelOut,
    TelegramValidateChatRequest,
    TelegramSendTestRequest,
    TelegramBotTestResponse,
    TelegramSendTestResponse,
    DiscoverChatsResponse,
    DiscoveredChat,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


def _get_channel_manager() -> ChannelManager:
    svc = get_telegram_service()
    return svc.channel_manager


def _require_telegram_service():
    try:
        return get_telegram_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── Channels ──────────────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[TelegramChannelOut])
async def list_channels(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[TelegramChannelOut]:
    mgr = _get_channel_manager()
    channels = await mgr.list_channels(db, active_only=active_only)
    return [TelegramChannelOut.model_validate(c) for c in channels]


@router.post("/channels", response_model=TelegramChannelOut, status_code=201)
async def add_channel(
    payload: TelegramChannelCreate,
    db: AsyncSession = Depends(get_db),
) -> TelegramChannelOut:
    mgr = _get_channel_manager()

    existing = await mgr.get_channel_by_chat_id(db, payload.chat_id)
    if existing:
        raise HTTPException(status_code=409, detail="Channel with this chat_id already exists")

    channel = await mgr.create_channel(
        db,
        chat_id=payload.chat_id,
        name=payload.name,
        channel_type=payload.channel_type,
        description=payload.description,
        send_signals=payload.send_signals,
        send_ai=payload.send_ai,
        send_news=payload.send_news,
        cooldown_sec=payload.cooldown_sec,
    )
    await db.commit()
    await db.refresh(channel)
    return TelegramChannelOut.model_validate(channel)


@router.get("/channels/{channel_id}", response_model=TelegramChannelOut)
async def get_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
) -> TelegramChannelOut:
    mgr = _get_channel_manager()
    channel = await mgr.get_channel(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return TelegramChannelOut.model_validate(channel)


@router.put("/channels/{channel_id}", response_model=TelegramChannelOut)
async def update_channel(
    channel_id: int,
    payload: TelegramChannelUpdate,
    db: AsyncSession = Depends(get_db),
) -> TelegramChannelOut:
    mgr = _get_channel_manager()
    channel = await mgr.update_channel(
        db, channel_id, **payload.model_dump(exclude_unset=True)
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.commit()
    await db.refresh(channel)
    return TelegramChannelOut.model_validate(channel)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    mgr = _get_channel_manager()
    ok = await mgr.delete_channel(db, channel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.commit()


# ── Bot connection tests ──────────────────────────────────────────────────────

@router.post("/test", response_model=TelegramBotTestResponse)
async def test_bot_connection() -> TelegramBotTestResponse:
    """Verify the configured bot token is valid."""
    svc = _require_telegram_service()
    result = await svc.test_connection()
    if not result.get("ok"):
        raise HTTPException(
            status_code=503,
            detail=result.get("error", "Bot connection failed"),
        )
    return TelegramBotTestResponse(**result)


@router.post("/validate", response_model=dict)
async def validate_chat(payload: TelegramValidateChatRequest) -> dict:
    """Validate that the bot has access to the given chat_id."""
    svc = _require_telegram_service()
    return await svc.validate_channel(payload.chat_id.strip())


@router.post("/send-test", response_model=TelegramSendTestResponse)
async def send_test_message(payload: TelegramSendTestRequest) -> TelegramSendTestResponse:
    """Send a test message to a specific chat_id."""
    chat_id = payload.chat_id.strip()
    svc = _require_telegram_service()
    try:
        result = await svc.send_raw(chat_id, payload.text)
        return TelegramSendTestResponse(ok=True, message_id=result.get("message_id"))
    except Exception as exc:
        return TelegramSendTestResponse(ok=False, error=str(exc))


# ── Chat discovery ────────────────────────────────────────────────────────────

@router.get("/discover", response_model=DiscoverChatsResponse)
async def discover_chats(
    db: AsyncSession = Depends(get_db),
) -> DiscoverChatsResponse:
    """
    Discover chats the bot has recently received messages from.

    Someone must send a message in the group/channel after the bot was added.
    """
    svc = _require_telegram_service()

    try:
        update_list = await svc.get_recent_updates(limit=100)
    except Exception as exc:
        return DiscoverChatsResponse(ok=False, chats=[], error=str(exc))

    seen: dict[int, dict] = {}
    for upd in update_list:
        for key in ("message", "channel_post", "my_chat_member", "chat_member"):
            msg = upd.get(key)
            if not msg:
                continue
            chat = msg.get("chat") or msg.get("new_chat_member", {}).get("chat")
            if not chat:
                continue
            cid = chat.get("id")
            if cid and cid not in seen:
                seen[cid] = {
                    "chat_id": str(cid),
                    "title": chat.get("title") or chat.get("first_name") or str(cid),
                    "type": chat.get("type", "unknown"),
                    "username": chat.get("username"),
                }

    mgr = _get_channel_manager()
    existing = await mgr.list_channels(db, active_only=False)
    existing_chat_ids = {c.chat_id for c in existing}

    chats: list[DiscoveredChat] = []
    for chat in seen.values():
        chats.append(DiscoveredChat(
            chat_id=chat["chat_id"],
            title=chat["title"],
            type=chat["type"],
            username=chat.get("username"),
            already_added=(
                chat["chat_id"] in existing_chat_ids
                or f"@{chat.get('username')}" in existing_chat_ids
            ),
        ))

    chats.sort(key=lambda x: x.title)
    hint = None
    if not chats:
        hint = (
            "No chats found. Make sure someone sent a message in the group "
            "after the bot was added, then try again."
        )

    return DiscoverChatsResponse(ok=True, chats=chats, total=len(chats), hint=hint)
