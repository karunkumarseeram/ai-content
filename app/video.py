import base64
import subprocess
import textwrap
from pathlib import Path

from google import genai
from openai import OpenAI

from app.schemas import NewsDraft


class VideoGenerator:
    def __init__(
        self,
        gemini_api_key: str,
        gemini_model: str,
        openai_api_key: str,
        tts_model: str,
        ffmpeg_bin: str,
    ) -> None:
        if not gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required to generate video clips.")
        if not openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required to generate narration.")
        self.gemini = genai.Client(api_key=gemini_api_key)
        self.gemini_model = gemini_model
        self.openai = OpenAI(api_key=openai_api_key)
        self.tts_model = tts_model
        self.ffmpeg_bin = ffmpeg_bin

    def create(
        self,
        draft: NewsDraft,
        video_path: Path,
        work_dir: Path,
    ) -> None:
        clip_paths: list[Path] = []
        for index, beat in enumerate(draft.beats):
            interaction = self.gemini.interactions.create(
                model=self.gemini_model,
                input=(
                    "Create a vertical 9:16, approximately 10-second abstract "
                    "editorial illustration for a news explainer. It must not look "
                    "like real footage or depict a real person, politician, or "
                    "specific news event. No readable text, logos, or fake news "
                    f"graphics. Visual idea: {beat.visual_prompt}"
                ),
            )
            video_data = getattr(interaction, "output_video", None)
            if not video_data or not video_data.data:
                raise RuntimeError(f"Gemini returned no video for news beat {index + 1}.")
            clip_path = work_dir / f"clip-{index + 1}.mp4"
            clip_path.write_bytes(base64.b64decode(video_data.data))
            clip_paths.append(clip_path)

        narration_path = work_dir / "narration.mp3"
        with self.openai.audio.speech.with_streaming_response.create(
            model=self.tts_model,
            voice="coral",
            input=draft.script,
            instructions="Read like a clear, brisk, neutral Indian English news presenter.",
            response_format="mp3",
        ) as response:
            response.stream_to_file(narration_path)

        normalized_paths = []
        for index, clip_path in enumerate(clip_paths):
            normalized_path = work_dir / f"normalized-{index + 1}.mp4"
            self._run_ffmpeg(
                [
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(clip_path),
                    "-t",
                    "10",
                    "-vf",
                    "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,setsar=1",
                    "-an",
                    "-r",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                    str(normalized_path),
                ],
                work_dir,
            )
            normalized_paths.append(normalized_path)

        concat_file = work_dir / "clips.txt"
        concat_file.write_text(
            "".join(f"file '{path.name}'\n" for path in normalized_paths),
            encoding="utf-8",
        )
        visuals_path = work_dir / "visuals.mp4"
        self._run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_file.name,
                "-c",
                "copy",
                str(visuals_path),
            ],
            work_dir,
        )

        captions_path = work_dir / "captions.srt"
        self._write_captions(draft, captions_path)
        self._run_ffmpeg(
            [
                "-i",
                str(visuals_path),
                "-i",
                str(narration_path),
                "-vf",
                "subtitles=captions.srt:force_style="
                "'FontName=DejaVu Sans,FontSize=18,Outline=2,Shadow=1,Alignment=2,MarginV=240'",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-shortest",
                str(video_path),
            ],
            work_dir,
        )
        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not produce a video file.")

    def _run_ffmpeg(self, args: list[str], cwd: Path) -> None:
        result = subprocess.run(
            [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            details = result.stderr.strip()[-1200:]
            raise RuntimeError(f"FFmpeg failed with exit code {result.returncode}: {details}")

    @staticmethod
    def _write_captions(draft: NewsDraft, path: Path) -> None:
        total_words = sum(max(1, len(beat.narration.split())) for beat in draft.beats)
        elapsed = 0.0
        cues = []
        for index, beat in enumerate(draft.beats, start=1):
            duration = 60 * max(1, len(beat.narration.split())) / total_words
            start = elapsed
            end = min(60.0, elapsed + duration)
            elapsed = end
            caption = textwrap.fill(beat.narration, width=48)
            cues.append(
                f"{index}\n{VideoGenerator._timestamp(start)} --> "
                f"{VideoGenerator._timestamp(end)}\n{caption}\n"
            )
        path.write_text("\n".join(cues), encoding="utf-8")

    @staticmethod
    def _timestamp(seconds: float) -> str:
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds_part, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02}:{minutes:02}:{seconds_part:02},{milliseconds:03}"
