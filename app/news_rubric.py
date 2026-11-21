from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.schemas import Article

MAX_STORY_AGE = timedelta(hours=24)
FUTURE_STORY_TOLERANCE = timedelta(minutes=5)

ANCHOR_COVERAGE = (
    ("local and regional India", ("local", "regional", "state", "city")),
    ("national and governance", ("india", "national", "politic", "governance", "policy")),
    ("international", ("world", "international", "global")),
)

ROTATING_SECTOR_COVERAGE = (
    ("business and economy", ("business", "economy", "market", "finance", "industry")),
    ("agriculture", ("agriculture", "agri", "farm", "rural")),
    ("health", ("health", "medicine", "medical")),
    ("education and jobs", ("education", "job", "employment")),
    ("technology", ("technology", "tech", "gadget", "digital")),
    ("science and environment", ("science", "environment", "climate")),
    ("sports and culture", ("sport", "culture")),
    ("energy and infrastructure", ("energy", "infrastructure", "transport")),
    ("law and society", ("law", "court", "society", "crime")),
)

NEWS_CURATION_RUBRIC = """
You are the fact-first editor for 104Dairies, a one-minute India-to-world news
brief. The input contains RSS items and the briefing date. Use only those items;
never add facts, context, names, figures, quotes, or claims from memory. Only
use items published in the last 24 hours, as indicated by their timestamps.

Coverage rubric:
1. Prefer one fresh local/regional India story, one national/governance story,
   and one international story when each is available.
2. Fill the remaining slots with fresh items from varied sectors: business and
   economy, agriculture, health, education and jobs, technology, science and
   environment, sports and culture, energy and infrastructure, and law/society.
   Rotate sector emphasis using the briefing date; do not default to technology
   or business every day. Never force a sector without a supported fresh item.
3. Select 4 to 6 distinct, consequential stories. Avoid duplicate events and
   repeated sectors when alternatives exist. Prefer diverse publishers.
4. Use neutral language, distinguish allegations from established facts, and
   avoid sensationalism. Each beat must cite exact article IDs from the input.
5. Write 95 to 140 spoken English words total, including opening and closing.
   Keep narration concise and understandable when read aloud.
6. Every visual prompt must describe an abstract, clearly illustrative scene,
   not a realistic depiction of a real person, politician, event, or breaking
   news footage; do not request text in the image.

Return only a JSON object with opening, closing, and beats. Each beat has
headline, narration, source_ids, and visual_prompt.
""".strip()


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_current_article(article: Article, now: datetime | None = None) -> bool:
    if article.published_at is None:
        return False
    current_time = _utc_datetime(now or datetime.now(timezone.utc))
    published_at = _utc_datetime(article.published_at)
    return (
        current_time - MAX_STORY_AGE
        < published_at
        <= current_time + FUTURE_STORY_TOLERANCE
    )


def select_daily_articles(
    articles: list[Article],
    today: date | None = None,
    now: datetime | None = None,
) -> list[Article]:
    today = today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    current = _utc_datetime(now or datetime.now(timezone.utc))
    fresh_articles = [
        article
        for article in articles
        if is_current_article(article, current)
    ]

    def published_order(article: Article) -> datetime:
        if article.published_at is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return _utc_datetime(article.published_at)

    fresh_articles.sort(key=published_order, reverse=True)

    selected: list[Article] = []
    selected_ids: set[str] = set()
    selected_titles: set[str] = set()

    def add_from_group(group: tuple[str, tuple[str, ...]]) -> None:
        _, terms = group
        article = next(
            (
                item
                for item in fresh_articles
                if item.article_id not in selected_ids
                and " ".join(item.title.casefold().split()) not in selected_titles
                and any(term in item.category.casefold() for term in terms)
            ),
            None,
        )
        if article is not None:
            selected.append(article)
            selected_ids.add(article.article_id)
            selected_titles.add(" ".join(article.title.casefold().split()))

    for group in ANCHOR_COVERAGE:
        add_from_group(group)

    offset = today.toordinal() % len(ROTATING_SECTOR_COVERAGE)
    rotating_groups = ROTATING_SECTOR_COVERAGE[offset:] + ROTATING_SECTOR_COVERAGE[:offset]
    for group in rotating_groups:
        if len(selected) >= 6:
            break
        add_from_group(group)

    for article in fresh_articles:
        if len(selected) >= 6:
            break
        title_key = " ".join(article.title.casefold().split())
        if article.article_id in selected_ids or title_key in selected_titles:
            continue
        selected.append(article)
        selected_ids.add(article.article_id)
        selected_titles.add(title_key)

    if len(selected) < 4:
        raise RuntimeError(
            "Daily news generation needs at least four distinct RSS stories "
            "published in the last 24 hours; "
            f"found {len(selected)}."
        )
    return selected
