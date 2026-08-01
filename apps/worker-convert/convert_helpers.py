"""Helper utilities and typed models for conversion."""

from __future__ import annotations

import json
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

ConversionStatus = Literal["converted", "skipped", "failed"]
_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".m4a", ".webm", ".mp4", ".opus", ".ogg", ".wav", ".flac", ".aac", ".mp3"}
)


@dataclass(frozen=True)
class ConversionInput:
    target_format: str
    bitrate_kbps: int
    remove_original_format: bool


class ConvertedItem(BaseModel):
    index: int = Field(ge=1)
    video_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    folder_name: str = Field(min_length=1)
    input_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    status: ConversionStatus
    removed_original: bool = False
    error: str | None = None

    @field_validator(
        "video_id", "title", "url", "folder_name", "input_path", "output_path"
    )
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


class ConversionResult(BaseModel):
    manifest_path: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    items: list[ConvertedItem]

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


def build_conversion_input(config: dict[str, Any] | None = None) -> ConversionInput:
    effective_config = config or load_config()
    conversion_cfg = effective_config.get("conversion", {})

    target_format = str(conversion_cfg.get("target_format", "mp3")).strip().lstrip(".")
    if not target_format:
        target_format = "mp3"

    bitrate_kbps = int(conversion_cfg.get("bitrate_kbps", 192))
    remove_original_format = bool(conversion_cfg.get("remove_original_format", False))

    return ConversionInput(
        target_format=target_format,
        bitrate_kbps=bitrate_kbps,
        remove_original_format=remove_original_format,
    )


def find_convertible_audio_file(item_output_dir: Path, target_format: str) -> Path | None:
    target_suffix = f".{target_format.lower()}"
    candidates: list[Path] = []

    for candidate in sorted(item_output_dir.iterdir()):
        if not candidate.is_file():
            continue
        suffix = candidate.suffix.lower()
        if suffix not in _AUDIO_EXTENSIONS:
            continue
        if suffix == target_suffix:
            continue
        candidates.append(candidate)

    return candidates[0] if candidates else None


def find_existing_target_file(item_output_dir: Path, target_format: str) -> Path | None:
    target_suffix = f".{target_format.lower()}"
    for candidate in sorted(item_output_dir.iterdir()):
        if candidate.is_file() and candidate.suffix.lower() == target_suffix:
            return candidate
    return None


def normalize_item_file_names(item_output_dir: Path) -> None:
    """Rename files in-place so names do not contain whitespace."""
    for candidate in sorted(item_output_dir.iterdir()):
        if not candidate.is_file():
            continue

        normalized_name = "_".join(candidate.name.split())
        if normalized_name == candidate.name:
            continue

        target = candidate.with_name(normalized_name)
        suffix = 1
        while target.exists():
            target = candidate.with_name(f"{target.stem}_{suffix}{target.suffix}")
            suffix += 1

        candidate.rename(target)
