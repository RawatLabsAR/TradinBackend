"""Read-only queries for whale scanner web API."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.whale_scan import WhaleScanCandidate, WhaleScanNotification, WhaleScanRun
from app.onchain.models.entities import WhaleWallet
from app.onchain.types import normalize_address
from app.whale_scanner.settings import whale_scan_settings

_BUY_TYPES = frozenset({"LARGE_BUY", "ACCUMULATION", "COORDINATED_ACTIVITY"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(dt: datetime | None = None) -> datetime:
    """UTC naive datetime for columns stored as TIMESTAMP WITHOUT TIME ZONE."""
    value = dt or _now()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _score(events: list[WhaleWallet]) -> tuple[float, float]:
    if not events:
        return 0.0, 0.0
    max_usd = max(e.usd_value for e in events)
    buys = sum(1 for e in events if e.event_type in _BUY_TYPES)
    return max_usd + buys * 10_000, max_usd


@dataclass
class EventSummary:
    event_type: str
    count: int


@dataclass
class WhaleScanHit:
    chain: str
    contract_address: str
    symbol: str | None
    token_name: str | None
    dex: str | None
    liquidity_usd: float
    volume_24h: float
    age_hours: float
    last_scanned_at: datetime | None
    max_usd: float
    score: float
    event_summary: list[EventSummary] = field(default_factory=list)
    notified_at: datetime | None = None


@dataclass
class WhaleScanOverview:
    last_run_at: str
    last_run_status: str
    tokens_scanned: int
    whales_detected: int
    hits_count: int
    threshold_usd: float
    lookback_hours: int
    max_age_days: int


@dataclass
class WhaleScanDetail:
    candidate: WhaleScanCandidate
    events: list[WhaleWallet]
    total_events: int
    max_usd: float
    score: float
    event_summary: list[EventSummary]


def _summarize_events(events: list[WhaleWallet]) -> list[EventSummary]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        counts[event.event_type] += 1
    return [
        EventSummary(event_type=etype, count=count)
        for etype, count in sorted(counts.items(), key=lambda x: -x[1])
    ]


async def _latest_run(db: AsyncSession) -> WhaleScanRun | None:
    result = await db.execute(
        select(WhaleScanRun).order_by(desc(WhaleScanRun.started_at)).limit(1)
    )
    return result.scalar_one_or_none()


async def _build_hits(
    db: AsyncSession,
    *,
    chain: str | None,
    hours: int,
) -> list[WhaleScanHit]:
    since = _naive_utc() - timedelta(hours=hours)
    max_age = whale_scan_settings.max_age_hours
    first_seen_cutoff = _now() - timedelta(days=whale_scan_settings.MAX_AGE_DAYS)

    candidate_filters = [
        (WhaleScanCandidate.age_hours <= max_age)
        | (WhaleScanCandidate.age_hours <= 0)
        | (WhaleScanCandidate.first_seen_at >= first_seen_cutoff),
    ]
    if chain:
        candidate_filters.append(WhaleScanCandidate.chain == chain.lower())

    candidate_result = await db.execute(select(WhaleScanCandidate).where(*candidate_filters))
    candidates = list(candidate_result.scalars().all())
    if not candidates:
        return []

    candidate_keys: dict[tuple[str, str], WhaleScanCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.chain.lower(),
            normalize_address(candidate.chain, candidate.contract_address),
        )
        candidate_keys[key] = candidate

    chains = {key[0] for key in candidate_keys}
    whale_filters = [
        WhaleWallet.detected_at >= since,
        WhaleWallet.chain.in_(chains),
    ]
    whale_result = await db.execute(
        select(WhaleWallet).where(*whale_filters).order_by(desc(WhaleWallet.detected_at))
    )
    events = list(whale_result.scalars().all())

    grouped: dict[tuple[str, str], list[WhaleWallet]] = defaultdict(list)
    for event in events:
        key = (event.chain.lower(), normalize_address(event.chain, event.token_address))
        if key in candidate_keys:
            grouped[key].append(event)

    candidate_ids = [candidate.id for candidate in candidates if candidate.id is not None]
    notifications: dict[int, datetime] = {}
    if candidate_ids:
        notify_result = await db.execute(
            select(WhaleScanNotification).where(
                WhaleScanNotification.candidate_id.in_(candidate_ids),
            ).order_by(desc(WhaleScanNotification.notified_at))
        )
        for note in notify_result.scalars().all():
            if note.candidate_id not in notifications:
                notifications[note.candidate_id] = note.notified_at

    today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    hits: list[WhaleScanHit] = []
    for key, token_events in grouped.items():
        if not token_events:
            continue
        candidate = candidate_keys[key]
        score, max_usd = _score(token_events)
        notified_at = notifications.get(candidate.id)
        if notified_at and notified_at < today_start:
            notified_at = None
        hits.append(
            WhaleScanHit(
                chain=candidate.chain,
                contract_address=candidate.contract_address,
                symbol=candidate.symbol,
                token_name=candidate.token_name,
                dex=candidate.dex,
                liquidity_usd=candidate.liquidity_usd,
                volume_24h=candidate.volume_24h,
                age_hours=candidate.age_hours,
                last_scanned_at=candidate.last_scanned_at,
                max_usd=max_usd,
                score=score,
                event_summary=_summarize_events(token_events),
                notified_at=notified_at,
            )
        )

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits


async def get_hits(
    db: AsyncSession,
    *,
    chain: str | None = None,
    page: int = 1,
    page_size: int = 50,
    hours: int | None = None,
) -> tuple[list[WhaleScanHit], int, str]:
    lookback = hours or whale_scan_settings.WHALE_LOOKBACK_HOURS
    hits = await _build_hits(db, chain=chain, hours=lookback)
    total = len(hits)
    offset = (page - 1) * page_size
    page_items = hits[offset : offset + page_size]

    run = await _latest_run(db)
    scanned_at = _iso(run.finished_at if run and run.finished_at else run.started_at if run else _now())
    return page_items, total, scanned_at


async def get_overview(
    db: AsyncSession,
    *,
    hours: int | None = None,
) -> WhaleScanOverview:
    lookback = hours or whale_scan_settings.WHALE_LOOKBACK_HOURS
    hits = await _build_hits(db, chain=None, hours=lookback)
    run = await _latest_run(db)

    return WhaleScanOverview(
        last_run_at=_iso(run.finished_at if run and run.finished_at else run.started_at if run else None),
        last_run_status=run.status if run else "never",
        tokens_scanned=run.tokens_scanned if run else 0,
        whales_detected=run.whales_detected if run else 0,
        hits_count=len(hits),
        threshold_usd=whale_scan_settings.WHALE_THRESHOLD_USD,
        lookback_hours=lookback,
        max_age_days=whale_scan_settings.MAX_AGE_DAYS,
    )


async def get_candidate_detail(
    db: AsyncSession,
    chain: str,
    address: str,
    *,
    page: int = 1,
    page_size: int = 50,
    hours: int | None = None,
) -> WhaleScanDetail | None:
    chain = chain.lower()
    normalized = normalize_address(chain, address)
    lookback = hours or whale_scan_settings.WHALE_LOOKBACK_HOURS
    since = _naive_utc() - timedelta(hours=lookback)

    candidate_result = await db.execute(
        select(WhaleScanCandidate).where(WhaleScanCandidate.chain == chain)
    )
    candidate = None
    for row in candidate_result.scalars().all():
        if normalize_address(chain, row.contract_address) == normalized:
            candidate = row
            break
    if candidate is None:
        return None

    token_address = normalize_address(chain, candidate.contract_address)
    count_result = await db.execute(
        select(WhaleWallet).where(
            WhaleWallet.chain == chain,
            WhaleWallet.token_address == token_address,
            WhaleWallet.detected_at >= since,
        )
    )
    all_events = list(count_result.scalars().all())
    total = len(all_events)
    score, max_usd = _score(all_events)

    offset = (page - 1) * page_size
    events_result = await db.execute(
        select(WhaleWallet).where(
            WhaleWallet.chain == chain,
            WhaleWallet.token_address == token_address,
            WhaleWallet.detected_at >= since,
        )
        .order_by(desc(WhaleWallet.detected_at))
        .offset(offset)
        .limit(page_size)
    )
    events = list(events_result.scalars().all())

    return WhaleScanDetail(
        candidate=candidate,
        events=events,
        total_events=total,
        max_usd=max_usd,
        score=score,
        event_summary=_summarize_events(all_events),
    )
