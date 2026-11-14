import json

from openai import OpenAI

from app.schemas import Article, NewsDraft


class NewsEditor:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required to curate the news script.")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def create_draft(self, articles: list[Article]) -> NewsDraft:
        source_data = [
            {
                "id": article.article_id,
                "category": article.category,
                "source": article.source,
                "title": article.title,
                "summary": article.summary,
                "url": article.url,
            }
            for article in articles
        ]
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                "You are the fact-first editor for 104Dairies, an Indian daily news "
                "brief. Use only facts explicitly present in the supplied RSS items. "
                "Do not add current events, numbers, quotes, names, context, or claims "
                "from memory. Select 4 to 6 genuinely important and varied stories, "
                "favoring India, regional India, politics, international news, "
                "technology/gadgets, business, science, and sports when supported by "
                "the feed. Do not force a category when there is no supported story. "
                "Use neutral language, distinguish allegations from established facts, "
                "and avoid sensationalism. Each beat must cite one or more exact article "
                "IDs from the input. Write an English script of 115 to 130 spoken "
                "words total, including opening and closing, suitable for a brisk "
                "one-minute news video. Every visual prompt must describe an abstract, "
                "clearly illustrative scene: no realistic depiction of a real person, "
                "politician, event, or breaking-news footage; no text in the image. "
                "Return only a JSON object with opening, closing, and beats. Each beat "
                "has headline, narration, source_ids, and visual_prompt."
            ),
            input=json.dumps(source_data, ensure_ascii=False),
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
