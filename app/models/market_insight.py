from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class MarketInsight(Base):
    """
    Curated, human-readable market insights derived from AI analysis.
    Designed to be extensible — future AI chatbot and alert features
    can write rows here.
    """

    __tablename__ = "market_insights"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    insight_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # SUMMARY | RISK | CATALYST | ALERT | VOLATILITY
    content: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    # info | warning | critical
    ai_summary_id: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_market_insight_symbol", "symbol"),
        Index("idx_market_insight_type", "insight_type"),
        Index("idx_market_insight_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<MarketInsight {self.symbol}/{self.insight_type}>"
