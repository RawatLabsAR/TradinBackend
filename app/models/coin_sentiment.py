from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class CoinSentiment(Base):
    """
    Rolling current-sentiment snapshot — one row per symbol (upserted).
    Fast lookup for the dashboard sentiment indicator without scanning
    the full ai_summaries history table.
    """

    __tablename__ = "coin_sentiment"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), default="neutral")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    ai_summary_id: Mapped[int] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_coin_sentiment_symbol", "symbol"),
        Index("idx_coin_sentiment_updated", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<CoinSentiment {self.symbol}: {self.sentiment} ({self.confidence}%)>"
