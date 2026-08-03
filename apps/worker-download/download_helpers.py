"""Helper utilities and typed models for downloading."""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# isort: off
# ROOT must be added to sys.path before importing config; keep these together
# so Ruff's import-sorter never hoists the import above the path mutation.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.config_loader import load_config  # noqa: E402
# isort: on

DownloadStatus = Literal["downloaded", "skipped", "failed"]


@dataclass(frozen=True)
class DownloadItemInput:
    index: int
    video_id: str
    title: str
    url: str
    folder_name: str
    config: dict[str, Any] | None = None


class DownloadedItem(BaseModel):
    index: int = Field(ge=1)
    video_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    folder_name: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    status: DownloadStatus
    error: str | None = None

    @field_validator("video_id", "title", "url", "folder_name", "output_path")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


class DownloadResult(BaseModel):
    manifest_path: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    items: list[DownloadedItem]

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

    if not isinstance(data, list):
        raise ValueError(f"Manifest file '{manifest_path}' must contain a JSON array")

    return data


def build_item_output_dir(output_dir: Path, folder_name: str) -> Path:
    return output_dir / folder_name


def sanitize_output_stem(title: str) -> str:
    cleaned = title.strip()
    cleaned = cleaned.replace("ß", "ss")
    cleaned = cleaned.replace("ä", "a")
    cleaned = cleaned.replace("ö", "o")
    cleaned = cleaned.replace("ü", "u")
    cleaned = cleaned.replace("Ä", "A")
    cleaned = cleaned.replace("Ö", "O")
    cleaned = cleaned.replace("Ü", "U")
    cleaned = cleaned.replace("ï", "i")
    cleaned = cleaned.replace("ë", "e")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "untitled"


def build_yt_dlp_download_options(
    item_output_dir: Path, config: dict[str, Any] | None = None
) -> Any:
    effective_config = config or load_config()
    download_cfg = effective_config.get("download", {})
    return {
        "format": download_cfg.get("audio_format_selector", "bestaudio"),
        "outtmpl": str(item_output_dir / f"%(title)s.%(ext)s"),
        "writethumbnail": download_cfg.get("write_thumbnail", True),
        "writeinfojson": download_cfg.get("write_info_json", True),
        "writedescription": download_cfg.get("write_description", True),
        "writesubtitles": download_cfg.get("write_subtitles", True),
        "subtitleslangs": download_cfg.get("subtitle_languages", []),
        "quiet": True,
        "no_warnings": True,
    }


def item_already_downloaded(item_output_dir: Path) -> bool:
    return item_output_dir.exists() and any(item_output_dir.iterdir())


def clear_existing_output_dir(item_output_dir: Path) -> None:
    if item_output_dir.exists():
        shutil.rmtree(item_output_dir)
