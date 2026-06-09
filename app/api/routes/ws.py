"""
Frontend WebSocket endpoint.

Protocol:
  Client → Server:
    { "action": "subscribe",   "product_ids": ["BTC-USD", ...] }
    { "action": "unsubscribe", "product_ids": ["BTC-USD", ...] }
    { "action": "ping" }

  Server → Client:
    { "type": "connected",    "client_id": "..." }
    { "type": "subscribed",   "product_ids": [...] }
    { "type": "ticker",       "data": { ...ticker fields... } }
    { "type": "pong" }
    { "type": "error",        "message": "..." }
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import ws_manager
from app.websocket.registry import get_active_ws_client

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    client_id = await ws_manager.connect(websocket)

    try:
        await ws_manager.send_to_client(client_id, {
            "type": "connected",
            "client_id": client_id,
        })

        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws_manager.send_to_client(client_id, {
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue

            action = msg.get("action", "")

            if action == "subscribe":
                product_ids = msg.get("product_ids", [])
                if not isinstance(product_ids, list) or not product_ids:
                    await ws_manager.send_to_client(client_id, {
                        "type": "error",
                        "message": "product_ids must be a non-empty list",
                    })
                    continue

                product_ids = [p.upper() for p in product_ids]
                await ws_manager.subscribe(client_id, product_ids)

                # Ensure the active exchange WS client is subscribed to these products
                ws_client = get_active_ws_client()
                if ws_client:
                    ws_client.add_products(product_ids)

                await ws_manager.send_to_client(client_id, {
                    "type": "subscribed",
                    "product_ids": product_ids,
                })

            elif action == "unsubscribe":
                product_ids = [p.upper() for p in msg.get("product_ids", [])]
                await ws_manager.unsubscribe(client_id, product_ids)

            elif action == "ping":
                await ws_manager.send_to_client(client_id, {"type": "pong"})

            else:
                await ws_manager.send_to_client(client_id, {
                    "type": "error",
                    "message": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        logger.info("Client %s disconnected cleanly", client_id)
    except Exception as exc:
        logger.error("WebSocket error for client %s: %s", client_id, exc)
    finally:
        await ws_manager.disconnect(client_id)
