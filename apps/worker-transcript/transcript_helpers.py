"""Helper utilities and typed models for transcription."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None

# isort: off
# ROOT must be added to sys.path before importing config; keep these together
# so Ruff's import-sorter never hoists the import above the path mutation.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORKER_DIR = Path(__file__).resolve().parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from config.config_loader import load_config  # noqa: E402
# isort: on

TranscriptStatus = Literal["transcribed", "skipped", "failed"]


@dataclass(frozen=True)
class TranscriptInput:
    output_text_file: str
    prefer_manual_subtitles: bool
    fallback_to_auto_subtitles: bool


class TranscriptedItem(BaseModel):
    index: int = Field(ge=1)
    video_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    folder_name: str = Field(min_length=1)
    transcript_path: str = Field(min_length=1)
    status: TranscriptStatus
    error: str | None = None

    @field_validator("video_id", "title", "url", "folder_name", "transcript_path")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


class TranscriptResult(BaseModel):
    manifest_path: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    items: list[TranscriptedItem]

    @field_validator("manifest_path", "output_dir")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


def load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items

    raise ValueError(
        f"Manifest file '{manifest_path}' must contain a JSON array or an object with an 'items' array"
    )


def build_item_output_dir(output_dir: Path, folder_name: str) -> Path:
    return output_dir / folder_name


def build_transcript_input(config: dict[str, Any] | None = None) -> TranscriptInput:
    effective_config = config or load_config()
    transcript_cfg = effective_config.get("transcript", {})
    return TranscriptInput(
        output_text_file=str(transcript_cfg.get("output_text_file", "transcript.txt")),
        prefer_manual_subtitles=bool(transcript_cfg.get("prefer_manual_subtitles", True)),
        fallback_to_auto_subtitles=bool(transcript_cfg.get("fallback_to_auto_subtitles", True)),
    )


def find_subtitle_files(item_output_dir: Path) -> list[Path]:
    subtitle_files = []
    for candidate in sorted(item_output_dir.iterdir()):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() in {".vtt", ".srt", ".txt"}:
            subtitle_files.append(candidate)
    return subtitle_files


_TAG_RE = re.compile(r"<[^>]+>")
_TIMING_RE = re.compile(r"\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}")


def extract_plain_text_from_subtitles(content: str) -> str:
    """Strip VTT/SRT cue metadata and inline tags, keeping only spoken text lines."""
    text_lines: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT":
            continue
        if line.startswith(("Kind:", "Language:", "NOTE", "STYLE")):
            continue
        if _TIMING_RE.search(line):
            continue
        if line.isdigit():
            continue

        cleaned = _TAG_RE.sub("", line).strip()
        if cleaned:
            text_lines.append(cleaned)

    # Auto-generated captions repeat the previous line as context for each new
    # cue, so drop consecutive duplicates to avoid repeated text.
    deduped_lines: list[str] = []
    for line in text_lines:
        if deduped_lines and deduped_lines[-1] == line:
            continue
        deduped_lines.append(line)

    return "\n".join(deduped_lines)


def write_transcript_from_subtitles(item_output_dir: Path, transcript_path: Path, subtitle_files: list[Path]) -> None:
    if not subtitle_files:
        return

    preferred_subtitle = subtitle_files[0]
    content = preferred_subtitle.read_text(encoding="utf-8")

    if preferred_subtitle.suffix.lower() in {".vtt", ".srt"}:
        content = extract_plain_text_from_subtitles(content)

    transcript_path.write_text(content, encoding="utf-8")


def find_transcript_output_path(item_output_dir: Path, output_text_file: str) -> Path:
    return item_output_dir / output_text_file


def build_yt_dlp_subtitle_options(
    item_output_dir: Path,
    subtitle_languages: list[str],
    *,
    auto_generated: bool,
) -> dict[str, Any]:
    return {
        "skip_download": True,
        "writesubtitles": not auto_generated,
        "writeautomaticsub": auto_generated,
        "subtitleslangs": subtitle_languages or ["en"],
        "subtitlesformat": "vtt",
        "outtmpl": str(item_output_dir / "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }


def fetch_subtitles_from_url(
    url: str,
    item_output_dir: Path,
    subtitle_languages: list[str],
    *,
    auto_generated: bool,
) -> str | None:
    """Download subtitle/caption files for `url` via yt-dlp. Returns an error message on failure, None on success."""
    if yt_dlp is None:
        return "yt-dlp is not installed"

    options = build_yt_dlp_subtitle_options(
        item_output_dir, subtitle_languages, auto_generated=auto_generated
    )
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])
    except (yt_dlp.utils.DownloadError, OSError, ValueError) as exc:
        return str(exc)

    return None
