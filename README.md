# 104Dairies Daily News

Production-oriented Python service for Render. It gathers RSS articles, asks
OpenAI to curate an English news script with source links, uses Gemini to create
illustrative clips, adds narration and captions, then publishes to YouTube
Shorts and Instagram Reels.

## Production architecture

```text
Render Web Service (one instance, one worker)
  ├─ Manual trigger: protected POST /jobs/run
  ├─ Neon PostgreSQL: job, script, source, and publishing status records
  └─ Render Persistent Disk (/var/data): temporary generated MP4
       └─ Public HTTPS /media/{job-id}.mp4 for Instagram to fetch

RSS -> OpenAI script/editor -> Gemini clips -> OpenAI voice -> FFmpeg
                                                   ├─ YouTube Data API
                                                   └─ Instagram Graph API
```

No Docker, local PostgreSQL, or always-on local computer is needed. Render runs
the app continuously; Neon stores job records. The generated MP4 and the
database record are retained until you manually clean them. Removing a database
row or local file does not delete or modify a published YouTube video or
Instagram Reel.

The Render service uses a persistent disk because Instagram needs an HTTPS URL
to fetch the MP4 at publish time. This app does not schedule publishing. On
Windows development, `/jobs/generate` uses free RSS feeds and a built-in
coverage rubric to create a locally voiced, locally illustrated video and save
its story/source record to the dev database. It does not call AI APIs or
publish. The separate `/jobs/run` pipeline uses paid AI APIs and publishes to
both platforms; it is not the free generate-only workflow.

The free video renderer uses a consistent 9:16 editorial design: gradient
backdrops, branded title/source panels, and category-specific vector
illustrations. These are polished illustrative graphics, not AI-generated or
photographic depictions of the reported event.

## Deploy from Git to Render

1. Push this project to a private GitHub repository. Ensure `.env` is not
   committed; `.gitignore` excludes it. Do not commit OAuth client/token JSON.
2. Create a Neon project and copy its PostgreSQL connection string. Use the
   pooled connection string if available and require SSL.
3. In Render, choose **New → Blueprint**, connect the GitHub repository, and
   deploy `render.yaml`. The blueprint installs FFmpeg from `apt.txt`, builds
   the Python app, creates a paid web service and mounts a 10 GB persistent
   disk at `/var/data`.
4. In the Render service's **Environment** settings, enter these secret values:
   - `DATABASE_URL`: Neon PostgreSQL connection string.
   - `OPENAI_API_KEY` and `GEMINI_API_KEY`.
   - `INSTAGRAM_ACCOUNT_ID` and `INSTAGRAM_ACCESS_TOKEN`.
   - `GOOGLE_OAUTH_TOKEN_JSON` (prepare it in step 5).
   - `CONTROL_TOKEN`: a new, long random value used to protect manual job/status
     endpoints.
   - `PUBLIC_BASE_URL`: the public `https://<service>.onrender.com` URL from
     Render. Add this after the first deployment, then redeploy.
5. Set up YouTube OAuth once on your own computer:
   - Enable YouTube Data API v3 and create an OAuth Desktop client.
   - Save its client JSON as `data/client_secret.json` (never commit it).
   - Run `python -m app.oauth_setup` locally and complete Google's consent flow.
   - Copy the contents of `data/youtube-token.json` into Render's
     `GOOGLE_OAUTH_TOKEN_JSON` secret. Do not paste credentials into chat or
     commit them. The service persists refreshed tokens on its private Render
     disk.
6. Confirm the Instagram account is Professional (Business or Creator). In the
   Meta app, configure Instagram API with Unified Login, add the account as an
   Instagram Tester, and grant `instagram_basic` and
   `instagram_content_publish`. Generate the account token from the app's
   **Generate access tokens** section.
7. Check `https://<service>.onrender.com/health`. It should report both
   `status: ok` and `database: connected`.

`INSTAGRAM_ACCESS_TOKEN` must be the token generated for the Instagram account
through Unified Login. The publisher calls `graph.facebook.com`; an Instagram
Login token for `graph.instagram.com` is not interchangeable. The Meta
configuration may show a token as non-expiring, but it can still be revoked;
store it as a secret and never commit or share it.

`render.yaml` marks secrets `sync: false`, so they must be set in Render's
dashboard and are not copied from your local `.env`. The running application
does not need `GOOGLE_OAUTH_CLIENT_SECRETS`; only the one-time local OAuth
setup does. Keep `data/youtube-token.json` and all API keys private.

## Local checks (optional)

Local run is not required for production. To run tests on Windows:

```powershell
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -v
```

Tests use SQLite in memory. In development, `ENV=dev` uses the local `DB_USER`,
`DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and `DEV_DB_NAME` settings; a PostgreSQL
`DATABASE_URL` is ignored. In production, `ENV=prod` requires a PostgreSQL
`DATABASE_URL` (Neon in Render) and never falls back to SQLite. To start locally,
run `python run.py --env dev`; the runner enables reload and binds to
`127.0.0.1:8000`. Render uses `python run.py --env prod --port $PORT`, which
disables reload and binds to `0.0.0.0` for an externally reachable service.

The app's startup handler creates output folders and registers the health, job,
and media routers from `app.api`; it does not start a scheduler or create
tables. The publishing pipeline initializes the database before a job runs.
Database engine configuration lives in `app.db.database`, and SQLAlchemy
models live in `app.db.models`. Run `python run.py --env dev` from the project
root to load `.env` and start Uvicorn.

## Operations

```powershell
curl.exe -X POST https://<service>.onrender.com/jobs/run `
  -H "Authorization: Bearer YOUR_CONTROL_TOKEN"

curl.exe https://<service>.onrender.com/jobs/latest `
  -H "Authorization: Bearer YOUR_CONTROL_TOKEN"
```

On Windows dev, start `python run.py --env dev`, then call:

```powershell
curl.exe -X POST http://127.0.0.1:8000/jobs/generate `
  -H "Authorization: Bearer YOUR_CONTROL_TOKEN"
```

This fetches timestamped RSS stories from Google News topic feeds, The Hindu,
and BBC, keeping only items published within the last 24 hours. The rubric
prioritizes local/regional India, national/governance, and international news,
then rotates among business, agriculture, health, education/jobs, technology,
science/environment, sports/culture, energy/infrastructure, and law/society
by the India-local date. It selects at most six stories for the one-minute
brief, creates a local-voice video under `data/videos`, and records its script,
source URLs, timestamps, and filename in the dev database. It does not call AI
APIs or publish. The `/jobs/latest` endpoint returns that job.
The server console logs the generation job ID, fresh RSS count, selected story
count, and final video path; failed generation logs the exception.

Job logs are not automatically deleted. To manually clear local development
logs, connect to the `DEV_DB_NAME` database and run:

```sql
DELETE FROM news_jobs;
```

This removes database rows only; it does not delete local MP4 files or posts on
YouTube/Instagram. Make sure you are connected to the intended database before
running it.

A one-minute video cannot include every story or sector. The rubric aims for
geographic breadth and rotates sector coverage; it cannot guarantee every
department or region has fresh RSS items every day. Items without a verifiable
publication timestamp are excluded rather than presented as breaking news.

Manual `/jobs/run` creates and publishes immediately to both platforms.
`PUBLIC_BASE_URL` must be a public HTTPS address that Meta can use to fetch the
generated MP4; `localhost` is not reachable by Instagram. `/jobs/latest` returns
the newest job from Neon. `/health` is public for Render's health check; job
endpoints require the bearer token. The public `/media/{job-id}.mp4` endpoint
serves only generated videos whose job record still exists. Publisher failures
are stored per platform; the app never calls APIs that delete an already-
published social post.

The one-minute script selects a few important supported stories from the
configured feeds; it cannot cover every story across India and the world. The
feeds are a starting point and should be reviewed before unattended publishing.
AI visuals are illustrative rather than depictions of actual breaking-news
footage.
