import json
import logging
import time
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.schemas import NewsDraft
from app.settings import Settings

logger = logging.getLogger(__name__)
YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]


def _caption(draft: NewsDraft, article_map: dict[str, dict[str, str]]) -> str:
    source_lines = []
    seen = set()
    for beat in draft.beats:
        for source_id in beat.source_ids:
            article = article_map[source_id]
            if source_id not in seen:
                seen.add(source_id)
                source_lines.append(f"{article['source']}: {article['url']}")
    caption = (
        "Today's 60-second news briefing from 104Dairies.\n\n"
        + "\n".join(source_lines)
        + "\n\nAI-generated illustrative visuals. Verify details with the linked sources."
        "\n#104Dairies #IndiaNews #DailyNews #News"
    )
    return caption[:2200]


def publish_youtube(
    settings: Settings,
    video_path: Path,
    draft: NewsDraft,
    article_map: dict[str, dict[str, str]],
) -> str:
    token_file = settings.google_oauth_token_file
    if token_file.is_file():
        credentials = Credentials.from_authorized_user_file(
            str(token_file), YOUTUBE_UPLOAD_SCOPE
        )
    elif settings.google_oauth_token_json:
        credentials = Credentials.from_authorized_user_info(
            json.loads(settings.google_oauth_token_json), YOUTUBE_UPLOAD_SCOPE
        )
    else:
        raise RuntimeError(
            "YouTube OAuth token is missing; run `python -m app.oauth_setup` first."
        )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise RuntimeError(
            "YouTube OAuth token is invalid; rerun `python -m app.oauth_setup`."
        )

    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    headline = draft.beats[0].headline
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": f"India in 60 Seconds: {headline}"[:100],
                "description": _caption(draft, article_map),
                "categoryId": "25",
                "tags": ["104Dairies", "India News", "Daily News", "Shorts"],
            },
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube upload completed without returning a video ID.")
    return f"https://www.youtube.com/shorts/{video_id}"


def publish_instagram(
    settings: Settings,
    video_url: str,
    draft: NewsDraft,
    article_map: dict[str, dict[str, str]],
) -> str:
    if not settings.instagram_account_id or not settings.instagram_access_token:
        raise RuntimeError(
            "Instagram publishing needs INSTAGRAM_ACCOUNT_ID and INSTAGRAM_ACCESS_TOKEN."
        )
    if not settings.public_base_url.startswith("https://"):
        raise RuntimeError(
            "PUBLIC_BASE_URL must be an HTTPS URL reachable by Meta to fetch the video."
        )

    base = (
        f"https://graph.facebook.com/{settings.meta_graph_api_version}/"
        f"{settings.instagram_account_id}"
    )
    timeout = httpx.Timeout(30, read=30)
    with httpx.Client(timeout=timeout) as client:
        create_response = client.post(
            f"{base}/media",
            params={
                "video_url": video_url,
                "media_type": "REELS",
                "caption": _caption(draft, article_map),
                "share_to_feed": "true",
                "access_token": settings.instagram_access_token,
            },
        )
        container = _graph_response(create_response)
        container_id = container.get("id")
        if not container_id:
            raise RuntimeError("Instagram did not return a Reel media container ID.")

        for _ in range(60):
            status_response = client.get(
                f"https://graph.facebook.com/{settings.meta_graph_api_version}/{container_id}",
                params={
                    "fields": "status_code",
                    "access_token": settings.instagram_access_token,
                },
            )
            status = _graph_response(status_response).get("status_code")
            if status == "FINISHED":
                break
            if status in {"ERROR", "EXPIRED"}:
                raise RuntimeError(f"Instagram Reel processing returned {status}.")
            time.sleep(10)
        else:
            raise RuntimeError("Instagram Reel processing timed out after 10 minutes.")

        publish_response = client.post(
            f"{base}/media_publish",
            params={
                "creation_id": container_id,
                "access_token": settings.instagram_access_token,
            },
        )
        published = _graph_response(publish_response)
        media_id = published.get("id")
        if not media_id:
            raise RuntimeError("Instagram did not return a published Reel ID.")
        return f"https://www.instagram.com/reel/{media_id}/"


def _graph_response(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Instagram Graph API returned HTTP {response.status_code} with invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Instagram Graph API returned HTTP {response.status_code} with an unexpected response."
        )
    if not response.is_success or "error" in payload:
        error = payload.get("error", {})
        detail = error.get("message", "request failed") if isinstance(error, dict) else str(error)
        raise RuntimeError(
            f"Instagram Graph API returned HTTP {response.status_code}: {detail}"
        )
    return payload
