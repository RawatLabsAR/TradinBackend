"""On-chain analytics package init."""

from app.onchain.analytics.volume_analytics import compute_volume_metrics
from app.onchain.analytics.whale_detector import detect_whale_events
from app.onchain.analytics.smart_money_scorer import score_wallet, update_smart_money_registry
from app.onchain.analytics.signal_generator import generate_signals

__all__ = [
    "compute_volume_metrics",
    "detect_whale_events",
    "score_wallet",
    "update_smart_money_registry",
    "generate_signals",
]
