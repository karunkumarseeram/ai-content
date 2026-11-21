import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from app.news_rubric import NEWS_CURATION_RUBRIC
from app.schemas import Article, NewsDraft


class NewsEditor:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required to curate the news script.")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def create_draft(
        self, articles: list[Article], brief_date: date | None = None
    ) -> NewsDraft:
        source_data = [
            {
                "id": article.article_id,
                "category": article.category,
                "source": article.source,
                "title": article.title,
                "summary": article.summary,
                "url": article.url,
                "published_at": (
                    article.published_at.isoformat()
                    if article.published_at is not None
                    else None
                ),
            }
            for article in articles
        ]
        briefing_date = brief_date or datetime.now(ZoneInfo("Asia/Kolkata")).date()
        response = self.client.responses.create(
            model=self.model,
            instructions=NEWS_CURATION_RUBRIC,
            input=json.dumps(
                {"brief_date": briefing_date.isoformat(), "articles": source_data},
                ensure_ascii=False,
            ),
        )
        try:
            draft = NewsDraft.model_validate_json(response.output_text)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("OpenAI returned an invalid news-draft JSON response.") from exc

        article_ids = {article.article_id for article in articles}
        unknown_ids = {
            source_id
            for beat in draft.beats
            for source_id in beat.source_ids
            if source_id not in article_ids
        }
        if unknown_ids:
            raise RuntimeError("OpenAI cited article IDs that were not in the source feed.")
        if not 95 <= draft.word_count <= 140:
            raise RuntimeError(
                f"News script is {draft.word_count} words; expected 95 to 140 for a one-minute video."
            )
        return draft
