"""In-memory progress for active whale scan runs (polled by the web UI)."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WhaleScanProgress:
    run_id: int | None = None
    status: str = "idle"
    phase: str = ""
    phase_label: str = ""
    total: int = 0
    completed: int = 0
    candidates_found: int = 0
    tokens_scanned: int = 0
    whales_detected: int = 0
    messages_sent: int = 0
    current_token: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: str | None = None

    @property
    def percent(self) -> int:
        if self.total <= 0:
            if self.status in {"discovering", "notifying"}:
                return 0
            if self.status == "ok":
                return 100
            return 0
        return min(100, round((self.completed / self.total) * 100))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["percent"] = self.percent
        data["is_running"] = self.status in {"discovering", "scanning", "notifying"}
        return data


_state = WhaleScanProgress()
_lock = asyncio.Lock()


def snapshot() -> dict:
    return _state.to_dict()


def is_running() -> bool:
    return _state.status in {"discovering", "scanning", "notifying"}


async def set_run_id(run_id: int) -> None:
    async with _lock:
        _state.run_id = run_id


async def try_start(*, run_id: int) -> bool:
    async with _lock:
        if is_running():
            return False
        _state.run_id = run_id
        _state.status = "discovering"
        _state.phase = "discovering"
        _state.phase_label = "Discovering new token candidates…"
        _state.total = 0
        _state.completed = 0
        _state.candidates_found = 0
        _state.tokens_scanned = 0
        _state.whales_detected = 0
        _state.messages_sent = 0
        _state.current_token = ""
        _state.started_at = _now_iso()
        _state.finished_at = ""
        _state.error = None
        return True


async def set_discovered(count: int, batch_size: int) -> None:
    async with _lock:
        _state.candidates_found = count
        _state.status = "scanning"
        _state.phase = "scanning"
        _state.phase_label = f"Scanning tokens for whale activity (0/{batch_size})…"
        _state.total = batch_size
        _state.completed = 0


async def tick_scan(
    *,
    completed: int,
    total: int,
    token_label: str,
    whale_events: int,
    whales_detected: int,
) -> None:
    async with _lock:
        _state.status = "scanning"
        _state.phase = "scanning"
        _state.total = total
        _state.completed = completed
        _state.tokens_scanned = completed
        _state.current_token = token_label
        _state.whales_detected = whales_detected
        _state.phase_label = f"Scanning tokens ({completed}/{total}) — {token_label}"


async def set_notifying() -> None:
    async with _lock:
        _state.status = "notifying"
        _state.phase = "notifying"
        _state.phase_label = "Sending digest and saving results…"
        _state.current_token = ""
        _state.total = 1
        _state.completed = 0


async def finish_ok(*, stats: dict) -> None:
    async with _lock:
        _state.status = "ok"
        _state.phase = "done"
        _state.phase_label = "Whale scan complete"
        _state.candidates_found = int(stats.get("discovered") or _state.candidates_found)
        _state.tokens_scanned = int(stats.get("tokens_scanned") or _state.tokens_scanned)
        _state.whales_detected = int(stats.get("whale_hits") or _state.whales_detected)
        _state.messages_sent = int(stats.get("messages_sent") or 0)
        _state.completed = _state.total if _state.total > 0 else _state.tokens_scanned
        _state.finished_at = _now_iso()
        _state.current_token = ""


async def finish_failed(error: str) -> None:
    async with _lock:
        _state.status = "failed"
        _state.phase = "failed"
        _state.phase_label = "Whale scan failed"
        _state.error = error
        _state.finished_at = _now_iso()
        _state.current_token = ""


async def reset_idle() -> None:
    async with _lock:
        if is_running():
            return
        _state.status = "idle"
        _state.phase = ""
        _state.phase_label = ""
