import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.repository import get_job
from app.settings import Settings

router = APIRouter()


@router.get("/media/{filename}")
def media(filename: str) -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(status_code=404, detail="Media file not found.")
    settings = Settings.from_env()
    record = get_job(settings.database_url, filename[:-4])
    video_path = Path(settings.output_dir) / "videos" / filename
    if record is None or record.video_filename != filename or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found.")
    return FileResponse(video_path, media_type="video/mp4", filename=filename)
