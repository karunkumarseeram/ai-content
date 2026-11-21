import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()


DEFAULT_FEEDS = [
    {
        "category": "Local and regional India",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+regional+state+local+news+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "National and governance",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+national+government+politics+policy+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "International",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=world+international+news+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Business and economy",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+business+economy+markets+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Agriculture",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+agriculture+farming+rural+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Health",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+health+medicine+public+health+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Education and jobs",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+education+jobs+employment+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Technology",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+technology+gadgets+digital+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Science and environment",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+science+environment+climate+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Sports and culture",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+sports+culture+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Energy and infrastructure",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+energy+transport+infrastructure+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
    {
        "category": "Law and society",
        "source": "Google News RSS",
        "url": "https://news.google.com/rss/search?q=India+law+court+society+when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen",
    },
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
    timezone: str
    ffmpeg_bin: str

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("ENV", "dev").strip().lower()
        configured_database_url = os.getenv("DATABASE_URL", "").strip()

        if environment == "dev":
            if configured_database_url.startswith(("sqlite://", "sqlite:///")):
                database_url = configured_database_url
            else:
                database_url = ""
            db_values = {
                "DB_USER": os.getenv("DB_USER", ""),
                "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
                "DB_HOST": os.getenv("DB_HOST", ""),
                "DB_PORT": os.getenv("DB_PORT", ""),
                "DEV_DB_NAME": os.getenv("DEV_DB_NAME", ""),
            }
            if not database_url and any(db_values.values()):
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
        elif environment == "prod":
            database_url = configured_database_url
            if not database_url:
                raise ValueError(
                    "DATABASE_URL is required when ENV=prod; set it to the Neon PostgreSQL URL."
                )
            if not database_url.startswith(
                ("postgres://", "postgresql://", "postgresql+psycopg://")
            ):
                raise ValueError(
                    "DATABASE_URL must be a PostgreSQL URL when ENV=prod."
                )
        else:
            raise ValueError("ENV must be either 'dev' or 'prod'.")

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
            require_postgres=(
                environment == "prod"
                or os.getenv("REQUIRE_POSTGRES", "false").lower() == "true"
            ),
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
            timezone=os.getenv("TIMEZONE", "Asia/Kolkata"),
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        )
