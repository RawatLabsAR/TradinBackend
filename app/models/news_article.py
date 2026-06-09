from datetime import datetime
from sqlalchemy import String, Text, DateTime, JSON, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class NewsArticle(Base):
    """
    Raw normalised news articles fetched from CryptoPanic / GNews.
    Deduplicated on external_id (provider's unique ID or URL hash).
    """

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    image_url: Mapped[str] = mapped_column(String(1024), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=True)
    source_domain: Mapped[str] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="news")
    symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    votes_positive: Mapped[int] = mapped_column(default=0)
    votes_negative: Mapped[int] = mapped_column(default=0)
    panic_score: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_news_external_id", "external_id"),
        Index("idx_news_published_at", "published_at"),
        Index("idx_news_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<NewsArticle {self.external_id}: {self.title[:50]}>"
