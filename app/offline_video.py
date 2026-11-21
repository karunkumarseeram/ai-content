import os
import subprocess
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.schemas import NewsDraft

WIDTH = 720
HEIGHT = 1280
FONT_DIR = Path(r"C:\Windows\Fonts")
BACKGROUND = (7, 17, 33)
WHITE = (244, 247, 252)
MUTED = (167, 185, 204)
PANEL = (14, 30, 51)
ACCENTS = {
    "india": (255, 170, 91),
    "regional": (255, 170, 91),
    "local and regional india": (255, 170, 91),
    "national and governance": (255, 170, 91),
    "politics": (190, 133, 255),
    "world": (82, 209, 229),
    "international": (82, 209, 229),
    "technology and gadgets": (82, 209, 229),
    "technology": (82, 209, 229),
    "business": (105, 224, 172),
    "business and economy": (105, 224, 172),
    "agriculture": (127, 204, 119),
    "health": (255, 126, 145),
    "education and jobs": (255, 192, 110),
    "science": (125, 179, 255),
    "science and environment": (125, 179, 255),
    "sports": (255, 207, 97),
    "sports and culture": (255, 207, 97),
}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_DIR / name
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_width: int,
    max_lines: int = 5,
) -> int:
    lines = _wrap(draw, text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;:") + "..."
    line_height = getattr(font, "size", 24) + 10
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _gradient_background(accent: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    top = (7, 16, 34)
    bottom = (12, 41, 63)
    for y in range(HEIGHT):
        blend = y / (HEIGHT - 1)
        color = tuple(
            round(top[channel] * (1 - blend) + bottom[channel] * blend)
            for channel in range(3)
        )
        draw.line((0, y, WIDTH, y), fill=color)

    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (330, 110, 870, 650),
        fill=(*accent, 32),
    )
    glow_draw.ellipse((-380, 680, 300, 1370), fill=(38, 111, 160, 24))
    glow = glow.filter(ImageFilter.GaussianBlur(75))
    image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")

    texture = ImageDraw.Draw(image, "RGBA")
    for x in range(24, WIDTH, 56):
        texture.line((x, 0, x, HEIGHT), fill=(175, 212, 240, 7), width=1)
    for y in range(20, HEIGHT, 56):
        texture.line((0, y, WIDTH, y), fill=(175, 212, 240, 7), width=1)
    return image


def _draw_globe(draw: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    draw.ellipse((260, 235, 460, 435), fill=(17, 57, 78), outline=accent, width=5)
    draw.arc((300, 235, 420, 435), 70, 290, fill=WHITE, width=3)
    draw.arc((300, 235, 420, 435), 250, 110, fill=WHITE, width=3)
    draw.arc((260, 280, 460, 390), 0, 180, fill=WHITE, width=3)
    draw.arc((260, 280, 460, 390), 180, 360, fill=WHITE, width=3)
    draw.polygon(
        [(300, 285), (330, 270), (350, 290), (341, 310), (317, 315), (308, 338), (287, 326)],
        fill=(*accent, 170),
    )
    draw.polygon(
        [(383, 344), (410, 330), (427, 347), (415, 370), (396, 375)],
        fill=(*accent, 170),
    )


def _draw_hero_art(
    image: Image.Image,
    category: str,
    accent: tuple[int, int, int],
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((150, 178, 570, 590), outline=(150, 193, 221, 30), width=2)
    draw.ellipse((185, 213, 535, 555), outline=(150, 193, 221, 45), width=2)
    draw.ellipse((233, 255, 487, 509), fill=(17, 44, 66, 240), outline=(*accent, 170), width=2)
    draw.ellipse((274, 296, 446, 468), fill=(*accent, 22))
    normalized = category.casefold()

    if any(term in normalized for term in ("world", "international", "global")):
        _draw_globe(draw, accent)
    elif any(term in normalized for term in ("regional", "local", "state", "city")):
        draw.ellipse((292, 255, 428, 391), outline=accent, width=8)
        draw.ellipse((328, 291, 392, 355), fill=(*accent, 120), outline=WHITE, width=4)
        draw.polygon([(292, 333), (428, 333), (360, 465)], fill=(*accent, 70), outline=accent)
        draw.ellipse((344, 307, 376, 339), fill=WHITE)
    elif any(term in normalized for term in ("national", "india", "governance", "politic", "policy")):
        draw.polygon([(266, 328), (360, 268), (454, 328)], fill=(*accent, 110), outline=accent)
        draw.rectangle((277, 328, 443, 423), fill=(31, 72, 94), outline=WHITE, width=3)
        for x in (296, 337, 379, 420):
            draw.rounded_rectangle((x, 341, x + 20, 414), radius=8, fill=(*accent, 200))
        draw.rectangle((258, 421, 462, 438), fill=WHITE)
        draw.rectangle((274, 443, 446, 455), fill=(*accent, 220))
    elif any(term in normalized for term in ("technology", "tech", "gadget", "digital")):
        draw.rounded_rectangle((306, 242, 414, 424), radius=24, fill=(9, 24, 42), outline=accent, width=7)
        draw.rounded_rectangle((320, 263, 400, 390), radius=14, fill=(26, 73, 91), outline=WHITE, width=2)
        draw.ellipse((353, 400, 367, 414), fill=WHITE)
        for x, y in ((271, 287), (449, 310), (280, 408), (438, 390)):
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=accent)
            draw.line((x, y, 309 if x < 360 else 411, y), fill=(*accent, 180), width=3)
    elif any(term in normalized for term in ("business", "economy", "market", "finance")):
        draw.line((278, 430, 442, 430), fill=WHITE, width=4)
        draw.line((278, 430, 278, 290), fill=WHITE, width=4)
        for x, top in ((302, 370), (342, 340), (382, 315), (422, 275)):
            draw.rounded_rectangle((x, top, x + 24, 426), radius=7, fill=(*accent, 210))
        draw.line((300, 348, 348, 322, 386, 332, 431, 278), fill=WHITE, width=5)
        draw.polygon([(431, 278), (414, 282), (428, 296)], fill=WHITE)
    elif any(term in normalized for term in ("agriculture", "agri", "farm", "rural")):
        draw.line((360, 430, 360, 288), fill=(*accent, 255), width=8)
        for box, leaf in (
            ((280, 300, 365, 365), 0),
            ((357, 270, 445, 338), 1),
            ((278, 370, 360, 420), 0),
            ((360, 350, 445, 410), 1),
        ):
            draw.ellipse(box, fill=(*accent, 135), outline=WHITE, width=3)
            x1, y1, x2, y2 = box
            start = (x1 + 12, y2 - 12) if not leaf else (x2 - 12, y2 - 12)
            end = (x2 - 12, y1 + 12) if not leaf else (x1 + 12, y1 + 12)
            draw.line((*start, *end), fill=WHITE, width=3)
    elif any(term in normalized for term in ("health", "medicine", "medical")):
        draw.rounded_rectangle((300, 267, 420, 414), radius=24, fill=(28, 62, 81), outline=accent, width=5)
        draw.rounded_rectangle((347, 289, 373, 355), radius=7, fill=WHITE)
        draw.rounded_rectangle((327, 309, 393, 335), radius=7, fill=WHITE)
        draw.line((302, 380, 329, 380, 341, 362, 356, 396, 372, 372, 388, 380, 418, 380), fill=accent, width=6)
    elif any(term in normalized for term in ("education", "job", "employment")):
        draw.polygon([(278, 294), (354, 314), (354, 426), (278, 405)], fill=(30, 68, 89), outline=accent)
        draw.polygon([(366, 314), (442, 294), (442, 405), (366, 426)], fill=(30, 68, 89), outline=accent)
        draw.line((360, 315, 360, 426), fill=WHITE, width=4)
        for y in (338, 360, 382):
            draw.line((294, y, 340, y + 12), fill=WHITE, width=3)
            draw.line((380, y + 12, 426, y), fill=WHITE, width=3)
        draw.polygon([(319, 263), (360, 246), (401, 263), (360, 280)], fill=(*accent, 210))
        draw.line((401, 263, 401, 291), fill=WHITE, width=3)
    elif any(term in normalized for term in ("science", "environment", "climate")):
        draw.ellipse((300, 275, 420, 395), outline=accent, width=5)
        draw.ellipse((318, 293, 402, 377), outline=WHITE, width=3)
        draw.ellipse((342, 317, 378, 353), fill=(*accent, 220))
        draw.ellipse((276, 335, 292, 351), fill=WHITE)
        draw.ellipse((428, 335, 444, 351), fill=WHITE)
        draw.ellipse((352, 255, 368, 271), fill=WHITE)
        draw.ellipse((352, 399, 368, 415), fill=WHITE)
        draw.line((292, 343, 428, 343), fill=(*accent, 190), width=3)
        draw.line((360, 271, 360, 399), fill=(*accent, 190), width=3)
    elif any(term in normalized for term in ("sport", "culture")):
        draw.ellipse((292, 262, 428, 398), fill=(28, 66, 88), outline=accent, width=6)
        draw.polygon(
            [(360, 300), (388, 320), (378, 353), (342, 353), (332, 320)],
            outline=WHITE,
            fill=(*accent, 100),
        )
        for points in (
            [(360, 300), (360, 277), (392, 266)],
            [(388, 320), (411, 312), (428, 330)],
            [(378, 353), (390, 376), (380, 396)],
            [(342, 353), (330, 376), (340, 396)],
            [(332, 320), (309, 312), (292, 330)],
        ):
            draw.line(points, fill=WHITE, width=4)
    elif any(term in normalized for term in ("energy", "infrastructure", "transport")):
        draw.rectangle((282, 350, 326, 425), fill=(*accent, 150), outline=WHITE, width=2)
        draw.rectangle((338, 315, 382, 425), fill=(31, 72, 94), outline=accent, width=3)
        draw.rectangle((394, 330, 438, 425), fill=(*accent, 150), outline=WHITE, width=2)
        for x in (294, 350, 406):
            for y in (365, 389):
                draw.rectangle((x, y, x + 10, y + 12), fill=WHITE)
        draw.line((270, 428, 450, 428), fill=WHITE, width=5)
    else:
        draw.line((360, 275, 360, 423), fill=WHITE, width=7)
        draw.line((307, 310, 413, 310), fill=accent, width=7)
        draw.polygon([(360, 276), (344, 300), (376, 300)], fill=accent)
        draw.line((320, 310, 297, 363), fill=WHITE, width=4)
        draw.line((400, 310, 423, 363), fill=WHITE, width=4)
        draw.arc((272, 345, 322, 380), 0, 180, fill=accent, width=6)
        draw.arc((398, 345, 448, 380), 0, 180, fill=accent, width=6)
        draw.line((330, 432, 390, 432), fill=WHITE, width=7)
    for x, y in ((206, 364), (514, 362), (360, 200), (360, 566)):
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(*accent, 210))


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    while text and draw.textbbox((0, 0), text, font=font)[2] > max_width:
        text = text[:-4].rstrip() + "..."
    return text


def _draw_header(
    draw: ImageDraw.ImageDraw,
    accent: tuple[int, int, int],
    brief_date: str,
    story_number: int | None,
    story_count: int | None,
) -> None:
    bold = _font("segoeuib.ttf", 23)
    regular = _font("segoeui.ttf", 17)
    draw.rounded_rectangle((42, 42, 82, 82), radius=13, fill=accent)
    draw.text((62, 62), "104", font=_font("segoeuib.ttf", 12), fill=BACKGROUND, anchor="mm")
    draw.text((98, 43), "104DAIRIES", font=bold, fill=WHITE)
    draw.text((99, 72), "DAILY NEWS BRIEF", font=regular, fill=MUTED)
    date_text = _fit_text(draw, brief_date.upper(), regular, 160)
    draw.text((WIDTH - 44, 55), date_text, font=regular, fill=MUTED, anchor="ra")
    if story_number is not None and story_count is not None:
        draw.rounded_rectangle(
            (WIDTH - 139, 86, WIDTH - 43, 119),
            radius=15,
            fill=(20, 44, 64),
            outline=(65, 98, 123),
            width=1,
        )
        draw.text(
            (WIDTH - 91, 103),
            f"{story_number:02d} / {story_count:02d}",
            font=_font("segoeuib.ttf", 15),
            fill=accent,
            anchor="mm",
        )
    draw.line((44, 137, WIDTH - 44, 137), fill=(66, 95, 119), width=1)


def _make_slide(
    headline: str,
    narration: str,
    category: str,
    source: str,
    output: Path,
    cover: bool = False,
    closing: bool = False,
    story_number: int | None = None,
    story_count: int | None = None,
    brief_date: str | None = None,
) -> None:
    accent = (83, 211, 221) if cover or closing else ACCENTS.get(category.casefold(), (83, 211, 221))
    image = _gradient_background(accent)
    draw = ImageDraw.Draw(image)
    date_label = brief_date or datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y")
    _draw_header(draw, accent, date_label, story_number, story_count)

    draw.rounded_rectangle(
        (42, 162, WIDTH - 42, 584),
        radius=34,
        fill=PANEL,
        outline=(55, 87, 112),
        width=2,
    )
    _draw_hero_art(image, "International" if cover or closing else category, accent)
    draw = ImageDraw.Draw(image)

    if cover:
        draw.rounded_rectangle(
            (74, 622, WIDTH - 74, 694),
            radius=24,
            fill=(18, 50, 70),
            outline=(*accent, 170),
            width=2,
        )
        draw.text((104, 658), "INDIA  /  WORLD  /  KEY SECTORS", font=_font("segoeuib.ttf", 19), fill=accent, anchor="lm")
        draw.text((70, 744), "THE DAY,", font=_font("segoeuib.ttf", 42), fill=MUTED)
        draw.text((70, 797), "IN FOCUS.", font=_font("segoeuib.ttf", 58), fill=WHITE)
        _draw_text(
            draw,
            "The latest stories from local communities to the wider world.",
            74,
            888,
            _font("segoeui.ttf", 27),
            MUTED,
            552,
            3,
        )
        draw.rounded_rectangle((74, 1040, 646, 1114), radius=22, fill=(18, 37, 58), outline=(56, 88, 112))
        draw.text((102, 1077), "FACT-FIRST  •  SOURCE-LINKED  •  60 SECONDS", font=_font("segoeuib.ttf", 16), fill=WHITE, anchor="lm")
    elif closing:
        draw.ellipse((295, 258, 425, 388), outline=accent, width=7)
        draw.line((325, 324, 350, 350, 397, 293), fill=WHITE, width=12, joint="curve")
        draw.text((74, 700), "STAY INFORMED.", font=_font("segoeuib.ttf", 44), fill=WHITE)
        draw.text((76, 764), "Stay curious.", font=_font("segoeui.ttf", 30), fill=accent)
        _draw_text(
            draw,
            "Open the saved job record for original story links.",
            76,
            840,
            _font("segoeui.ttf", 26),
            MUTED,
            550,
            3,
        )
        draw.rounded_rectangle((74, 1040, 646, 1114), radius=22, fill=(18, 37, 58), outline=(56, 88, 112))
        draw.text((102, 1077), "104DAIRIES  /  DAILY NEWS", font=_font("segoeuib.ttf", 18), fill=WHITE, anchor="lm")
    else:
        category_font = _font("segoeuib.ttf", 17)
        label = _fit_text(draw, category.upper(), category_font, 400)
        label_width = draw.textbbox((0, 0), label, font=category_font)[2]
        draw.rounded_rectangle((66, 613, 94 + label_width, 652), radius=18, fill=(20, 45, 65), outline=(*accent, 165), width=1)
        draw.ellipse((80, 628, 92, 640), fill=accent)
        draw.text((104, 632), label, font=category_font, fill=accent, anchor="lm")
        next_y = _draw_text(
            draw,
            headline,
            70,
            682,
            _font("segoeuib.ttf", 37),
            WHITE,
            580,
            3,
        )
        _draw_text(
            draw,
            narration,
            74,
            next_y + 18,
            _font("segoeui.ttf", 24),
            MUTED,
            565,
            5,
        )
        draw.rounded_rectangle((66, 1034, WIDTH - 66, 1131), radius=22, fill=(17, 38, 58), outline=(52, 83, 107), width=1)
        draw.rounded_rectangle((84, 1054, 94, 1110), radius=5, fill=accent)
        draw.text((112, 1054), "SOURCE", font=_font("segoeuib.ttf", 13), fill=MUTED)
        source_font = _font("segoeuib.ttf", 19)
        source_label = _fit_text(draw, source, source_font, 480)
        draw.text((112, 1082), source_label, font=source_font, fill=WHITE)

    draw.line((50, 1180, WIDTH - 50, 1180), fill=(55, 84, 108), width=1)
    draw.text((54, 1207), "EDITORIAL ILLUSTRATION  /  NOT NEWS FOOTAGE", font=_font("segoeui.ttf", 14), fill=MUTED)
    draw.text((WIDTH - 54, 1207), "104D", font=_font("segoeuib.ttf", 15), fill=accent, anchor="ra")
    image.save(output, format="PNG", optimize=True)


def _synthesize(parts: list[str], work_dir: Path) -> tuple[Path, list[float]]:
    if os.name != "nt":
        raise RuntimeError("Offline female narration is currently supported on Windows only.")
    import win32com.client

    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    voices = speaker.GetVoices()
    female_voice = next(
        (
            voices.Item(index)
            for index in range(voices.Count)
            if "zira" in voices.Item(index).GetDescription().lower()
            or "female" in voices.Item(index).GetDescription().lower()
        ),
        None,
    )
    if female_voice is None:
        raise RuntimeError("No installed female Windows speech voice was found.")
    speaker.Voice = female_voice
    speaker.Rate = 1
    speaker.Volume = 100

    audio_paths: list[Path] = []
    durations: list[float] = []
    for index, text in enumerate(parts):
        path = work_dir / f"voice-{index}.wav"
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(path), 3, False)
        speaker.AudioOutputStream = stream
        speaker.Speak(text)
        stream.Close()
        with wave.open(str(path), "rb") as audio:
            if audio.getcomptype() != "NONE":
                raise RuntimeError("Windows speech returned compressed WAV audio.")
            if audio_paths:
                with wave.open(str(audio_paths[0]), "rb") as first:
                    if (
                        audio.getframerate() != first.getframerate()
                        or audio.getnchannels() != first.getnchannels()
                        or audio.getsampwidth() != first.getsampwidth()
                    ):
                        raise RuntimeError("Narration segments use incompatible audio formats.")
            durations.append(audio.getnframes() / audio.getframerate())
        audio_paths.append(path)

    with wave.open(str(audio_paths[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
    for path in audio_paths[1:]:
        with wave.open(str(path), "rb") as audio:
            frames.append(audio.readframes(audio.getnframes()))
    narration_path = work_dir / "narration.wav"
    with wave.open(str(narration_path), "wb") as target:
        target.setparams(params)
        for chunk in frames:
            target.writeframes(chunk)
    return narration_path, durations


class OfflineVideoGenerator:
    def create(
        self,
        draft: NewsDraft,
        article_map: dict[str, dict[str, str | None]],
        video_path: Path,
        work_dir: Path,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("Offline video generation is currently supported on Windows only.")

        parts = [
            "Here is today's news briefing from India and around the world.",
            *(beat.narration for beat in draft.beats),
            "Those are today's leading stories. Check the original sources for details.",
        ]
        narration_path, durations = _synthesize(parts, work_dir)
        slides: list[Path] = []
        brief_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y")
        cover = work_dir / "slide-0.png"
        _make_slide("", "", "", "", cover, cover=True, brief_date=brief_date)
        slides.append(cover)

        for index, beat in enumerate(draft.beats, start=1):
            source = article_map[beat.source_ids[0]].get("source") or "News source"
            slide = work_dir / f"slide-{index}.png"
            category = next(
                (
                    article_map[source_id].get("category") or ""
                    for source_id in beat.source_ids
                    if source_id in article_map
                ),
                "",
            )
            _make_slide(
                beat.headline,
                beat.narration,
                category,
                source,
                slide,
                story_number=index,
                story_count=len(draft.beats),
                brief_date=brief_date,
            )
            slides.append(slide)

        closing = work_dir / f"slide-{len(draft.beats) + 1}.png"
        _make_slide("", "", "", "", closing, closing=True, brief_date=brief_date)
        slides.append(closing)

        concat_path = work_dir / "slides.txt"
        with concat_path.open("w", encoding="utf-8", newline="\n") as concat:
            for image, duration in zip(slides, durations):
                concat.write(f"file '{image.as_posix()}'\n")
                concat.write(f"duration {max(duration, 1.0):.3f}\n")
            concat.write(f"file '{slides[-1].as_posix()}'\n")

        video_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-i",
                str(narration_path),
                "-vf",
                "fps=24,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "25",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"FFmpeg failed: {result.stderr[-1600:]}")
        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not produce the news video.")
