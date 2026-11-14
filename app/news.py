import hashlib
import html
import logging
import re
from html.parser import HTMLParser

import feedparser
import httpx

from app.schemas import Article

logger = logging.getLogger(__name__)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()


def fetch_articles(feeds: list[dict[str, str]], limit: int = 40) -> list[Article]:
    articles: list[Article] = []
    seen_urls: set[str] = set()

    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "104DairiesNewsBot/1.0"},
    ) as client:
        for feed in feeds:
            try:
                response = client.get(feed["url"])
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning(
                    "Could not fetch news feed %s (%s): %s",
                    feed["source"],
                    feed["category"],
                    exc,
                )
                continue

            parsed = feedparser.parse(response.content)
            for entry in parsed.entries[:12]:
                url = str(entry.get("link", "")).strip()
                title = _plain_text(str(entry.get("title", "")))
                if not url or not title or url in seen_urls:
                    continue
                seen_urls.add(url)
                summary = _plain_text(
                    str(entry.get("summary", entry.get("description", "")))
                )
                article_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
                articles.append(
                    Article(
                        article_id=article_id,
                        title=title[:300],
                        summary=summary[:1200],
                        url=url,
                        category=feed["category"],
                        source=feed["source"],
                    )
                )
                if len(articles) >= limit:
                    return articles

    if not articles:
        raise RuntimeError(
            "No news articles were fetched. Check NEWS_FEEDS_JSON and network access."
        )
    return articles
