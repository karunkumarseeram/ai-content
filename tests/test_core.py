from datetime import datetime, timedelta, timezone
from dataclasses import replace
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.main import app
from app.news import _plain_text, fetch_articles
from app.news_rubric import select_daily_articles
from app.offline_video import _make_slide
from app.pipeline import (
    _create_offline_draft,
    prepare_daily_job,
    prepare_offline_news_job,
    publish_prepared_job,
    run_daily_job,
)
from app.publishers import publish_instagram
from app.db.database import get_engine
from app.db.init_db import init_db
from app.db.models import JobRecord
from app.repository import (
    create_job,
    delete_expired_jobs,
    get_job,
    get_latest_job,
    save_job,
)
from app.schemas import Article, NewsDraft, StoryBeat
from app.settings import Settings
from app.video import VideoGenerator
from run import main as run_application
from sqlalchemy.engine import make_url


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._environment_patch = patch.dict(os.environ, {"ENV": "dev"})
        cls._environment_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._environment_patch.stop()

    def test_run_entrypoint_selects_development_and_production_modes(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("run.uvicorn.run") as uvicorn_run:
                run_application(["--env", "dev", "--port", "8100"])
                self.assertEqual(os.environ["ENV"], "dev")
                self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.INFO)
                self.assertEqual(
                    uvicorn_run.call_args.kwargs,
                    {
                        "host": "127.0.0.1",
                        "port": 8100,
                        "reload": True,
                        "workers": 1,
                    },
                )

                run_application(["--env", "prod", "--port", "10000"])
                self.assertEqual(os.environ["ENV"], "prod")
                self.assertEqual(
                    uvicorn_run.call_args.kwargs,
                    {
                        "host": "0.0.0.0",
                        "port": 10000,
                        "reload": False,
                        "workers": 1,
                    },
                )

    def test_run_entrypoint_rejects_invalid_port(self) -> None:
        with patch("run.uvicorn.run") as uvicorn_run:
            with self.assertRaises(SystemExit):
                run_application(["--env", "prod", "--port", "70000"])
            uvicorn_run.assert_not_called()

    def test_run_entrypoint_uses_render_port_environment_variable(self) -> None:
        with patch.dict("os.environ", {"PORT": "10000"}, clear=True):
            with patch("run.uvicorn.run") as uvicorn_run:
                run_application(["--env", "prod"])

        self.assertEqual(uvicorn_run.call_args.kwargs["port"], 10000)

    def test_local_dev_database_settings_build_postgres_url(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENV": "dev",
                "DB_USER": "postgres",
                "DB_PASSWORD": "test:password",
                "DB_HOST": "localhost",
                "DB_PORT": "5432",
                "DEV_DB_NAME": "ai_content",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        url = make_url(settings.database_url)
        self.assertEqual(url.drivername, "postgresql+psycopg")
        self.assertEqual(url.username, "postgres")
        self.assertEqual(url.password, "test:password")
        self.assertEqual(url.host, "localhost")
        self.assertEqual(url.port, 5432)
        self.assertEqual(url.database, "ai_content")

    def test_dev_uses_local_database_settings_when_neon_url_is_set(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENV": "dev",
                "DATABASE_URL": "postgresql://neon-user:neon-password@neon.example/db",
                "DB_USER": "local-user",
                "DB_PASSWORD": "local-password",
                "DB_HOST": "localhost",
                "DB_PORT": "5432",
                "DEV_DB_NAME": "ai_content",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        url = make_url(settings.database_url)
        self.assertEqual(url.username, "local-user")
        self.assertEqual(url.password, "local-password")
        self.assertEqual(url.host, "localhost")
        self.assertEqual(url.database, "ai_content")

    def test_prod_uses_neon_database_url(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENV": "prod",
                "DATABASE_URL": "postgresql://neon-user:neon-password@neon.example/db",
                "DB_USER": "local-user",
                "DB_PASSWORD": "local-password",
                "DB_HOST": "localhost",
                "DB_PORT": "5432",
                "DEV_DB_NAME": "ai_content",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertEqual(
            settings.database_url,
            "postgresql://neon-user:neon-password@neon.example/db",
        )
        self.assertTrue(settings.require_postgres)

    def test_prod_requires_postgres_database_url(self) -> None:
        with patch.dict("os.environ", {"ENV": "prod"}, clear=True):
            with self.assertRaisesRegex(ValueError, "DATABASE_URL is required"):
                Settings.from_env()

        with patch.dict(
            "os.environ",
            {"ENV": "prod", "DATABASE_URL": "sqlite:///local.db"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be a PostgreSQL URL"):
                Settings.from_env()

    def test_plain_text_removes_markup_and_decodes_entities(self) -> None:
        self.assertEqual(
            _plain_text("<p>News&nbsp;&amp; updates<br>today</p>"),
            "News & updates today",
        )

    def test_rss_fetch_keeps_fresh_items_and_round_robins_categories(self) -> None:
        now = datetime.now(timezone.utc)

        class FakeResponse:
            def __init__(self, content: bytes) -> None:
                self.content = content

            def raise_for_status(self) -> None:
                return None

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def get(self, url: str) -> FakeResponse:
                return FakeResponse(url.encode("utf-8"))

        def parse_feed(content: bytes) -> SimpleNamespace:
            feed_name = content.decode("utf-8").rsplit("/", 1)[-1]
            return SimpleNamespace(
                entries=[
                    {
                        "link": f"https://news.example.test/{feed_name}/fresh",
                        "title": f"Fresh story from {feed_name}",
                        "summary": "A verified current news story.",
                        "published_parsed": time.gmtime(
                            (now - timedelta(minutes=10)).timestamp()
                        ),
                        "source": {"title": f"Publisher {feed_name}"},
                    },
                    {
                        "link": f"https://news.example.test/{feed_name}/old",
                        "title": f"Old story from {feed_name}",
                        "summary": "A story outside the freshness window.",
                        "published_parsed": time.gmtime(
                            (now - timedelta(days=2)).timestamp()
                        ),
                    },
                ]
            )

        feeds = [
            {
                "category": "Regional",
                "source": "RSS feed one",
                "url": "https://feed.example.test/one",
            },
            {
                "category": "International",
                "source": "RSS feed two",
                "url": "https://feed.example.test/two",
            },
        ]
        with (
            patch("app.news.httpx.Client", return_value=FakeClient()),
            patch("app.news.feedparser.parse", side_effect=parse_feed),
        ):
            articles = fetch_articles(feeds, limit=2)

        self.assertEqual([article.category for article in articles], ["Regional", "International"])
        self.assertTrue(all(article.published_at is not None for article in articles))
        self.assertEqual(articles[0].source, "Publisher one")
        self.assertNotIn("/old", " ".join(article.url for article in articles))

    def test_unified_login_publisher_uses_facebook_graph_api(self) -> None:
        settings = replace(
            Settings.from_env(),
            instagram_account_id="test-ig-account",
            instagram_access_token="test-instagram-user-token",
            public_base_url="https://news.example.test",
            meta_graph_api_version="v27.0",
        )
        draft = NewsDraft(
            opening="Here is today's update.",
            closing="That is the latest.",
            beats=[
                StoryBeat(
                    headline=f"Headline number {index}",
                    narration="This is a neutral, sourced news update for today.",
                    source_ids=["source-1"],
                    visual_prompt="Abstract illustration with neutral colors and motion.",
                )
                for index in range(1, 5)
            ],
        )
        created = MagicMock()
        created.is_success = True
        created.json.return_value = {"id": "test-container"}
        status = MagicMock()
        status.is_success = True
        status.json.return_value = {"status_code": "FINISHED"}
        published = MagicMock()
        published.is_success = True
        published.json.return_value = {"id": "test-media"}
        client = MagicMock()
        client.post.side_effect = [created, published]
        client.get.return_value = status

        with patch("app.publishers.httpx.Client") as http_client:
            http_client.return_value.__enter__.return_value = client
            result = publish_instagram(
                settings,
                "https://news.example.test/media/video.mp4",
                draft,
                {"source-1": {"source": "Example News", "url": "https://news.example.test/story"}},
            )

        self.assertEqual(result, "https://www.instagram.com/reel/test-media/")
        self.assertIn(
            "https://graph.facebook.com/v27.0/test-ig-account/media",
            client.post.call_args_list[0].args[0],
        )
        self.assertIn(
            "https://graph.facebook.com/v27.0/test-container",
            client.get.call_args.args[0],
        )
        self.assertIn(
            "https://graph.facebook.com/v27.0/test-ig-account/media_publish",
            client.post.call_args_list[1].args[0],
        )
        self.assertEqual(
            client.post.call_args_list[0].kwargs["params"]["media_type"], "REELS"
        )

    def test_news_script_is_composed_from_all_beats(self) -> None:
        draft = NewsDraft(
            opening="Here is today's update.",
            closing="That is the latest.",
            beats=[
                StoryBeat(
                    headline=f"Headline number {index}",
                    narration=f"Story {index} reports a verified update from today.",
                    source_ids=["source-1"],
                    visual_prompt="Abstract illustration with neutral colors and motion.",
                )
                for index in range(1, 5)
            ],
        )
        self.assertEqual(draft.script.split()[0], "Here")
        self.assertEqual(draft.script.split()[-1], "latest.")
        self.assertEqual(draft.word_count, len(draft.script.split()))

    def test_caption_timestamps_cover_one_minute(self) -> None:
        draft = NewsDraft(
            opening="Here is today's update.",
            closing="That is the latest.",
            beats=[
                StoryBeat(
                    headline=f"Headline number {index}",
                    narration="This is a neutral, sourced news update for today.",
                    source_ids=["source-1"],
                    visual_prompt="Abstract illustration with neutral colors and motion.",
                )
                for index in range(1, 5)
            ],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            caption_path = Path(temporary_directory) / "captions.srt"
            VideoGenerator._write_captions(draft, caption_path)
            captions = caption_path.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 -->", captions)
        self.assertIn("00:01:00,000", captions)
        self.assertEqual(captions.count(" --> "), 4)

    def test_api_protects_job_status_and_exposes_health(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                "os.environ",
                {
                    "CONTROL_TOKEN": "test-control-token",
                    "DATABASE_URL": "sqlite:///:memory:",
                    "OUTPUT_DIR": temporary_directory,
                },
            ):
                init_db(Settings.from_env())
                with TestClient(app) as client:
                    self.assertFalse(hasattr(app.state, "scheduler"))
                    self.assertEqual(client.get("/health").status_code, 200)
                    self.assertEqual(client.get("/jobs/latest").status_code, 401)
                    self.assertEqual(client.post("/jobs/generate").status_code, 401)
                    response = client.get(
                        "/jobs/latest",
                        headers={"Authorization": "Bearer test-control-token"},
                    )
                    self.assertEqual(response.status_code, 404)
                    with patch(
                        "app.api.jobs.prepare_offline_news_job",
                        return_value={"status": "ready"},
                    ) as generate_job:
                        response = client.post(
                            "/jobs/generate",
                            headers={"Authorization": "Bearer test-control-token"},
                        )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"status": "ready"})
                    generate_job.assert_called_once()

    def test_offline_draft_selects_diverse_sources_for_a_one_minute_brief(self) -> None:
        published_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        articles = [
            Article(
                article_id=f"article-{index}",
                title=f"News headline number {index}",
                summary=(
                    f"Story number {index} reports an important current development "
                    "with details from the source and additional context for readers."
                ),
                url=f"https://news.example.test/{index}",
                category=category,
                source="Example News",
                published_at=published_at,
            )
            for index, category in enumerate(
                ["India", "Politics", "Regional", "World", "Technology and gadgets", "Business", "Science", "Sports"],
                start=1,
            )
        ]

        draft = _create_offline_draft(articles)

        self.assertEqual(len(draft.beats), 6)
        self.assertGreaterEqual(draft.word_count, 95)
        self.assertLessEqual(draft.word_count, 140)
        self.assertEqual(len({beat.source_ids[0] for beat in draft.beats}), 6)
        self.assertIn("India and around the world", draft.opening)

    def test_daily_rubric_filters_old_stories_and_rotates_sector_slots(self) -> None:
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
        today = now.date()
        categories = [
            "Local and regional India",
            "National and governance",
            "International",
            "Business and economy",
            "Agriculture",
            "Health",
            "Education and jobs",
            "Technology",
            "Science and environment",
            "Sports and culture",
            "Energy and infrastructure",
            "Law and society",
        ]
        articles = [
            Article(
                article_id=f"rubric-{index}",
                title=f"Distinct current story number {index}",
                summary="A timely report with a verifiable source and useful facts.",
                url=f"https://news.example.test/rubric/{index}",
                category=category,
                source="Example News",
                published_at=now - timedelta(minutes=index),
            )
            for index, category in enumerate(categories, start=1)
        ]
        articles.append(
            Article(
                article_id="stale-story",
                title="A stale story that must not be used",
                summary="This story was published too long ago to qualify.",
                url="https://news.example.test/stale",
                category="Technology",
                source="Example News",
                published_at=now - timedelta(days=2),
            )
        )
        articles.append(
            Article(
                article_id="cutoff-story",
                title="A story exactly at the freshness cutoff",
                summary="This story is not within the last 24 hours.",
                url="https://news.example.test/cutoff",
                category="Health",
                source="Example News",
                published_at=now - timedelta(hours=24),
            )
        )

        day_one = select_daily_articles(articles, today=today, now=now)
        day_two = select_daily_articles(
            articles, today=today + timedelta(days=1), now=now
        )

        self.assertEqual(len(day_one), 6)
        self.assertEqual(len(day_two), 6)
        self.assertEqual(
            {article.category for article in day_one[:3]},
            {"Local and regional India", "National and governance", "International"},
        )
        self.assertNotIn("stale-story", {article.article_id for article in day_one})
        self.assertNotIn("cutoff-story", {article.article_id for article in day_one})
        self.assertNotEqual(
            {article.article_id for article in day_one},
            {article.article_id for article in day_two},
        )

    def test_offline_story_art_is_polished_portrait_and_category_specific(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            health_slide = Path(temporary_directory) / "health.png"
            technology_slide = Path(temporary_directory) / "technology.png"
            for output, category in (
                (health_slide, "Health"),
                (technology_slide, "Technology"),
            ):
                _make_slide(
                    "A major development in the sector",
                    "Officials announced a new update today with further details from the source.",
                    category,
                    "Example News",
                    output,
                    story_number=1,
                    story_count=6,
                    brief_date="21 Nov 2026",
                )
                with Image.open(output) as image:
                    self.assertEqual(image.size, (720, 1280))
                    self.assertGreater(len(image.getcolors(maxcolors=1_000_000) or []), 500)

            self.assertNotEqual(health_slide.read_bytes(), technology_slide.read_bytes())

    def test_offline_news_job_saves_video_and_sources_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            published_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            settings = replace(
                Settings.from_env(),
                database_url=f"sqlite:///{root / 'offline.db'}",
                require_postgres=False,
                output_dir=root / "data",
            )
            init_db(settings)
            historical_id = "c" * 32
            historical_job = {
                "id": historical_id,
                "status": "ready",
                "script": "A previously generated news briefing.",
                "platforms": {},
                "video_filename": f"{historical_id}.mp4",
            }
            create_job(settings.database_url, historical_job)
            save_job(settings.database_url, historical_job)
            with Session(get_engine(settings.database_url)) as session:
                historical_record = session.get(JobRecord, historical_id)
                self.assertIsNotNone(historical_record)
                historical_record.created_at = datetime.now(timezone.utc) - timedelta(days=2)
                session.commit()
            historical_video = root / "data" / "videos" / f"{historical_id}.mp4"
            historical_video.parent.mkdir(parents=True, exist_ok=True)
            historical_video.write_bytes(b"old local video")
            articles = [
                Article(
                    article_id=f"offline-{index}",
                    title=f"News headline number {index}",
                    summary=(
                        f"Story number {index} reports a current development from "
                        "its cited source with useful details for a short news briefing."
                    ),
                    url=f"https://news.example.test/offline/{index}",
                    category=category,
                    source="Example News",
                    published_at=published_at,
                )
                for index, category in enumerate(
                    ["India", "Regional", "World", "Technology and gadgets"],
                    start=1,
                )
            ]
            with (
                patch("app.pipeline.fetch_articles", return_value=articles),
                patch(
                    "app.offline_video.OfflineVideoGenerator.create",
                    autospec=True,
                    side_effect=lambda _self, _draft, _article_map, video_path, _work_dir:
                    video_path.write_bytes(b"offline video"),
                ),
                patch("app.pipeline.publish_youtube") as youtube_publish,
                patch("app.pipeline.publish_instagram") as instagram_publish,
            ):
                with self.assertLogs("app.pipeline", level="INFO") as job_logs:
                    result = prepare_offline_news_job(settings)

            record = get_job(settings.database_url, result["id"])
            self.assertTrue(any("fetched 4 fresh RSS stories" in line for line in job_logs.output))
            self.assertTrue(any("ready: video=" in line for line in job_logs.output))
            self.assertEqual(result["status"], "ready")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.status, "ready")
            self.assertEqual(record.article_count, 4)
            self.assertIn("India and around the world", record.script)
            self.assertIn("https://news.example.test/offline/1", record.articles["offline-1"]["url"])
            self.assertTrue(record.articles["offline-1"]["published_at"])
            self.assertTrue((root / "data" / "videos" / record.video_filename).is_file())
            self.assertIsNotNone(get_job(settings.database_url, historical_id))
            self.assertTrue(historical_video.is_file())
            self.assertEqual(record.platforms, {})
            youtube_publish.assert_not_called()
            instagram_publish.assert_not_called()
            get_engine(settings.database_url).dispose()

    def test_job_records_missing_credentials_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            settings = replace(
                Settings.from_env(),
                database_url="sqlite:///:memory:",
                output_dir=output_dir,
            )
            init_db(settings)
            expired_id = "b" * 32
            expired_job = {
                "id": expired_id,
                "status": "published",
                "video_filename": f"{expired_id}.mp4",
                "platforms": {
                    "youtube": {"status": "published", "url": "https://youtube.test/1"},
                    "instagram": {"status": "published", "url": "https://instagram.test/1"},
                },
            }
            create_job(settings.database_url, expired_job)
            save_job(settings.database_url, expired_job)
            with Session(get_engine(settings.database_url)) as session:
                record = session.get(JobRecord, expired_id)
                self.assertIsNotNone(record)
                record.created_at = datetime.now(timezone.utc) - timedelta(days=2)
                session.commit()
            old_video = output_dir / "videos" / f"{expired_id}.mp4"
            old_video.parent.mkdir(parents=True)
            old_video.write_bytes(b"old local video")

            settings = replace(
                settings,
                openai_api_key="",
                gemini_api_key="",
                instagram_account_id="",
                instagram_access_token="",
                google_oauth_token_file=output_dir / "missing-token.json",
                public_base_url="",
                output_dir=output_dir,
            )
            with (
                patch("app.pipeline.publish_youtube") as youtube_publish,
                patch("app.pipeline.publish_instagram") as instagram_publish,
            ):
                result = run_daily_job(settings)
            youtube_publish.assert_not_called()
            instagram_publish.assert_not_called()
            self.assertEqual(result["status"], "failed")
            self.assertIn("OPENAI_API_KEY", result["error"])
            self.assertTrue(old_video.exists())
            self.assertIsNotNone(get_job(settings.database_url, expired_id))
            latest = get_latest_job(settings.database_url)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.status, "failed")

    def test_scheduled_pipeline_prepares_then_publishes_saved_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            token_file = output_dir / "youtube-token.json"
            token_file.write_text("test token", encoding="utf-8")
            settings = replace(
                Settings.from_env(),
                openai_api_key="test-openai-key",
                gemini_api_key="test-gemini-key",
                database_url="sqlite:///:memory:",
                instagram_account_id="test-account",
                instagram_access_token="test-instagram-token",
                google_oauth_token_file=token_file,
                public_base_url="https://news.example.test",
                output_dir=output_dir,
            )
            article = Article(
                article_id="source-1",
                title="A supported national news headline",
                summary="A short verified summary from the feed.",
                url="https://news.example.test/story",
                category="India",
                source="Example News",
            )
            draft = NewsDraft(
                opening="Here is today's update.",
                closing="That is the latest.",
                beats=[
                    StoryBeat(
                        headline=f"Headline number {index}",
                        narration="This is a neutral, sourced news update for today.",
                        source_ids=["source-1"],
                        visual_prompt="Abstract illustration with neutral colors and motion.",
                    )
                    for index in range(1, 5)
                ],
            )
            editor = MagicMock()
            editor.create_draft.return_value = draft

            with (
                patch("app.pipeline.fetch_articles", return_value=[article]),
                patch("app.pipeline.NewsEditor", return_value=editor),
                patch("app.pipeline.VideoGenerator") as generator,
                patch(
                    "app.pipeline.publish_youtube",
                    return_value="https://youtube.example.test/shorts/1",
                ),
                patch(
                    "app.pipeline.publish_instagram",
                    return_value="https://instagram.example.test/reel/1/",
                ),
            ):
                generator.return_value.create.side_effect = (
                    lambda _draft, video_path, _working_directory: video_path.write_bytes(
                        b"test video"
                    )
                )
                prepared = prepare_daily_job(settings)
                self.assertEqual(prepared["status"], "ready")

                published = publish_prepared_job(settings)

            self.assertEqual(published["status"], "published")
            self.assertEqual(
                published["platforms"]["youtube"]["status"], "published"
            )
            self.assertEqual(
                published["platforms"]["instagram"]["status"], "published"
            )

    def test_expired_job_cleanup_removes_only_local_database_record(self) -> None:
        database_url = "sqlite:///:memory:"
        init_db(replace(Settings.from_env(), database_url=database_url))
        job_id = "a" * 32
        job = {
            "id": job_id,
            "status": "published",
            "video_filename": f"{job_id}.mp4",
            "platforms": {
                "youtube": {
                    "status": "published",
                    "url": "https://youtube.example.test/shorts/1",
                },
                "instagram": {
                    "status": "published",
                    "url": "https://instagram.example.test/reel/1/",
                },
            },
        }
        create_job(database_url, job)
        save_job(database_url, job)
        with Session(get_engine(database_url)) as session:
            record = session.get(JobRecord, job_id)
            self.assertIsNotNone(record)
            record.created_at = datetime.now(timezone.utc) - timedelta(days=2)
            session.commit()

        removed_videos = delete_expired_jobs(
            database_url, datetime.now(timezone.utc) - timedelta(days=1)
        )

        self.assertEqual(removed_videos, [f"{job_id}.mp4"])
        self.assertIsNone(get_job(database_url, job_id))
        self.assertEqual(
            job["platforms"]["youtube"]["url"],
            "https://youtube.example.test/shorts/1",
        )
        self.assertEqual(
            job["platforms"]["instagram"]["url"],
            "https://instagram.example.test/reel/1/",
        )


if __name__ == "__main__":
    unittest.main()
