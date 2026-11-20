from datetime import datetime, timedelta, timezone
from dataclasses import replace
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.news import _plain_text
from app.pipeline import prepare_daily_job, publish_prepared_job, run_daily_job
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
                    self.assertEqual(client.get("/health").status_code, 200)
                    self.assertEqual(client.get("/jobs/latest").status_code, 401)
                    response = client.get(
                        "/jobs/latest",
                        headers={"Authorization": "Bearer test-control-token"},
                    )
                    self.assertEqual(response.status_code, 404)

    def test_job_records_missing_credentials_before_external_calls(self) -> None:
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
            self.assertFalse(old_video.exists())
            self.assertIsNone(get_job(settings.database_url, expired_id))
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
