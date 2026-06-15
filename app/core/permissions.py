"""Role-based feature access.

Admin-only:
  - User management (/api/admin/*)
  - Discovery scan (POST /api/discover/scan)
  - Broadcast, signal broadcast, Telegram channel management
  - On-chain ETL sync (POST /api/onchain/sync/*)
  - Token Telegram broadcast alerts
  - Strategy run ``broadcast_telegram`` flag

User + admin (authenticated):
  - Dashboard, markets, analytics, AI, news, discovery browse
  - Own price alerts, own scripts (CRUD, run, backtest)
  - On-chain live analysis and read APIs
  - Token search and record-search
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.models.script import Script
from app.models.user import User


def is_admin(user: User) -> bool:
    return user.role == "admin"


def require_script_access(user: User, script: Script) -> None:
    if is_admin(user):
        return
    if script.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
