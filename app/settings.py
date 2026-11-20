import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()


DEFAULT_FEEDS = [
    {
        "category": "India",
        "source": "The Hindu",
        "url": "https://www.thehindu.com/news/national/feeder/default.rss",
    },
    {
        "category": "Politics",
        "source": "BBC News",
        "url": "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml",
    },
    {
        "category": "Regional",
        "source": "The Hindu",
        "url": "https://www.thehindu.com/news/states/feeder/default.rss",
    },
    {
        "category": "World",
        "source": "BBC News",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "category": "Technology and gadgets",
        "source": "The Hindu",
        "url": "https://www.thehindu.com/sci-tech/technology/feeder/default.rss",
    },
    {
        "category": "Business",
        "source": "The Hindu",
        "url": "https://www.thehindu.com/business/feeder/default.rss",
    },
    {
        "category": "Science",
        "source": "The Hindu",
        "url": "https://www.thehindu.com/sci-tech/science/feeder/default.rss",
    },
    {
        "category": "Sports",
        "source": "BBC News",
        "url": "https://feeds.bbci.co.uk/sport/rss.xml",
    },
]


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    openai_tts_model: str
    gemini_api_key: str
    gemini_video_model: str
    instagram_account_id: str
    instagram_access_token: str
    meta_graph_api_version: str
    public_base_url: str
    control_token: str
    database_url: str
    require_postgres: bool
    google_oauth_client_secrets: Path
    google_oauth_token_file: Path
    google_oauth_token_json: str
    output_dir: Path
    news_feeds: list[dict[str, str]]
    posting_time: str
    timezone: str
    ffmpeg_bin: str

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url and os.getenv("ENV", "").lower() == "dev":
            db_values = {
                "DB_USER": os.getenv("DB_USER", ""),
                "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
                "DB_HOST": os.getenv("DB_HOST", ""),
                "DB_PORT": os.getenv("DB_PORT", ""),
                "DEV_DB_NAME": os.getenv("DEV_DB_NAME", ""),
            }
            if any(db_values.values()):
                missing_db_values = [
                    name for name, value in db_values.items() if not value
                ]
                if missing_db_values:
                    raise ValueError(
                        "Local PostgreSQL settings are incomplete: "
                        + ", ".join(missing_db_values)
                    )
                database_url = URL.create(
                    drivername="postgresql+psycopg",
                    username=db_values["DB_USER"],
                    password=db_values["DB_PASSWORD"],
                    host=db_values["DB_HOST"],
                    port=int(db_values["DB_PORT"]),
                    database=db_values["DEV_DB_NAME"],
                ).render_as_string(hide_password=False)
        if not database_url:
            database_url = "sqlite:///data/104dairies.db"

        feeds_json = os.getenv("NEWS_FEEDS_JSON", "").strip()
        feeds = json.loads(feeds_json) if feeds_json else DEFAULT_FEEDS
        if not isinstance(feeds, list) or not all(
            isinstance(feed, dict)
            and all(key in feed for key in ("category", "source", "url"))
            for feed in feeds
        ):
            raise ValueError(
                "NEWS_FEEDS_JSON must be a JSON array with category, source, and url fields."
            )

        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_video_model=os.getenv(
                "GEMINI_VIDEO_MODEL", "gemini-omni-1.2-flash"
            ),
            instagram_account_id=os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
            instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", ""),
            meta_graph_api_version=os.getenv("META_GRAPH_API_VERSION", "v27.0"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            control_token=os.getenv("CONTROL_TOKEN", ""),
            database_url=database_url,
            require_postgres=os.getenv("REQUIRE_POSTGRES", "false").lower() == "true",
            google_oauth_client_secrets=Path(
                os.getenv(
                    "GOOGLE_OAUTH_CLIENT_SECRETS", "data/client_secret.json"
                )
            ),
            google_oauth_token_file=Path(
                os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "data/youtube-token.json")
            ),
            google_oauth_token_json=os.getenv("GOOGLE_OAUTH_TOKEN_JSON", ""),
            output_dir=Path(os.getenv("OUTPUT_DIR", "data")),
            news_feeds=feeds,
            posting_time=os.getenv("POSTING_TIME", "18:00"),
            timezone=os.getenv("TIMEZONE", "Asia/Kolkata"),
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        )
