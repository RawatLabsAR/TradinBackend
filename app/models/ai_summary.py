from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class AISummary(Base):
    """
    Cached AI-generated market analysis per coin symbol.
    A new row is inserted on each regeneration; the latest unexpired row
    is served as the current analysis.  Older rows provide historical data.
    """

    __tablename__ = "ai_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)

    # Core AI output fields
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str] = mapped_column(String(16), nullable=True)   # bullish | bearish | neutral
    confidence: Mapped[int] = mapped_column(Integer, default=0)          # 0–100
    positive_factors: Mapped[list] = mapped_column(JSON, default=list)
    negative_factors: Mapped[list] = mapped_column(JSON, default=list)
    market_impact: Mapped[str] = mapped_column(Text, nullable=True)
    key_events: Mapped[list] = mapped_column(JSON, default=list)

    # Processing metadata (for cost tracking + debugging)
    model_used: Mapped[str] = mapped_column(String(64), nullable=True)
    articles_processed: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Cache control
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_ai_summary_symbol", "symbol"),
        Index("idx_ai_summary_expires", "expires_at"),
        Index("idx_ai_summary_symbol_expires", "symbol", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<AISummary {self.symbol} sentiment={self.sentiment} conf={self.confidence}>"
