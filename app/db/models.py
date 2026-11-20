from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobRecord(Base):
    __tablename__ = "news_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    script: Mapped[str | None] = mapped_column(Text)
    script_word_count: Mapped[int | None] = mapped_column(Integer)
    opening: Mapped[str | None] = mapped_column(Text)
    closing: Mapped[str | None] = mapped_column(Text)
    beats: Mapped[list | None] = mapped_column(JSON)
    articles: Mapped[dict | None] = mapped_column(JSON)
    video_filename: Mapped[str | None] = mapped_column(String(100))
    platforms: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)

    def as_dict(self, output_dir: Path) -> dict:
        result = {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "article_count": self.article_count,
            "script": self.script,
            "script_word_count": self.script_word_count,
            "opening": self.opening,
            "closing": self.closing,
            "beats": self.beats or [],
            "articles": self.articles or {},
            "platforms": self.platforms or {},
            "error": self.error,
        }
        if self.video_filename:
            result["video_path"] = str(output_dir / "videos" / self.video_filename)
        if self.published_at:
            result["published_at"] = self.published_at.isoformat()
        return result
