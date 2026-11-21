from concurrent.futures import ThreadPoolExecutor
import calendar
import hashlib
import html
import logging
import re
from html.parser import HTMLParser
from datetime import datetime, timezone

import feedparser
import httpx

from app.schemas import Article
from app.news_rubric import is_current_article

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


def _published_at(entry: dict) -> datetime | None:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published is None:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(published), timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _fetch_feed(
    client: httpx.Client,
    feed: dict[str, str],
    current_time: datetime,
) -> list[Article]:
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
        return []

    articles: list[Article] = []
    parsed = feedparser.parse(response.content)
    for entry in parsed.entries:
        url = str(entry.get("link", "")).strip()
        title = _plain_text(str(entry.get("title", "")))
        if not url or not title:
            continue
        published_at = _published_at(entry)
        entry_source = entry.get("source")
        source_name = (
            _plain_text(str(entry_source.get("title", "")))
            if isinstance(entry_source, dict)
            else ""
        )
        article = Article(
            article_id=hashlib.sha256(url.encode("utf-8")).hexdigest()[:12],
            title=title[:300],
            summary=_plain_text(
                str(entry.get("summary", entry.get("description", "")))
            )[:1200],
            url=url,
            category=feed["category"],
            source=source_name or feed["source"],
            published_at=published_at,
        )
        if is_current_article(article, current_time):
            articles.append(article)

    articles.sort(
        key=lambda article: article.published_at
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return articles[:12]


def fetch_articles(feeds: list[dict[str, str]], limit: int = 40) -> list[Article]:
    current_time = datetime.now(timezone.utc)
    worker_count = min(8, len(feeds))
    if worker_count == 0:
        raise RuntimeError("No RSS news feeds are configured.")

    with httpx.Client(
        timeout=12,
        follow_redirects=True,
        headers={"User-Agent": "104DairiesNewsBot/1.0"},
    ) as client:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            feed_articles = list(
                executor.map(
                    lambda feed: _fetch_feed(client, feed, current_time),
                    feeds,
                )
            )

    articles: list[Article] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    while len(articles) < limit:
        added_in_round = False
        for feed_items in feed_articles:
            while feed_items:
                article = feed_items.pop(0)
                title_key = " ".join(article.title.casefold().split())
                if article.url in seen_urls or title_key in seen_titles:
                    continue
                seen_urls.add(article.url)
                seen_titles.add(title_key)
                articles.append(article)
                added_in_round = True
                break
            if len(articles) >= limit:
                break
        if not added_in_round:
            break

    if not articles:
        raise RuntimeError(
            "No news items were found with publication timestamps in the last "
            "24 hours. Check NEWS_FEEDS_JSON and network access."
        )
    return articles
