"""Helper utilities and typed models for discovery."""

from __future__ import annotations

import re
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

from config.config_loader import load_config, validate_required_mapping_fields  # noqa: E402
# isort: on

SourceType = Literal["single", "search", "playlist", "channel", "unknown"]


@dataclass(frozen=True)
class ManifestEntryInput:
    index: int
    video_id: str
    title: str
    url: str
    source_type: str = "single"
    config: dict[str, Any] | None = None


class ManifestEntry(BaseModel):
    index: int = Field(ge=1)
    video_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    folder_name: str = Field(min_length=1)
    source_type: SourceType

    @field_validator("video_id", "title", "url", "folder_name")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


class DiscoveryResult(BaseModel):
    source_type: SourceType
    source_url: str = Field(min_length=1)
    items: list[ManifestEntry]
    manifest_path: str = Field(min_length=1)

    @field_validator("source_url", "manifest_path")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


def sanitize_title(title: str, config: dict[str, Any] | None = None) -> str:
    if not title:
        return "untitled"

    title = title.strip()
    title = title.replace("ß", "ss")
    title = title.replace("ä", "a")
    title = title.replace("ö", "o")
    title = title.replace("ü", "u")
    title = title.replace("Ä", "A")
    title = title.replace("Ö", "O")
    title = title.replace("Ü", "U")
    title = title.replace("ï", "i")
    title = title.replace("ë", "e")

    replacement = "_"
    if config:
        naming = config.get("naming", {})
        replacement = naming.get("replace_whitespace_with", replacement)

    title = re.sub(r"[^A-Za-z0-9]+", replacement, title)
    title = re.sub(rf"{re.escape(replacement)}+", replacement, title).strip(replacement)
    return title or "untitled"


def build_item_folder_name(
    index: int,
    video_id: str,
    title: str,
    config: dict[str, Any] | None = None,
) -> str:
    effective_config = config or load_config()
    validate_required_mapping_fields(
        effective_config,
        "naming",
        {"item_folder_pattern", "safe_title_max_length", "replace_whitespace_with"},
        Path("config/settings.yaml"),
    )
    naming = effective_config.get("naming", {})
    pattern = naming.get("item_folder_pattern", "{index:04d}__{video_id}__{safe_title}")
    safe_title = sanitize_title(title, config=effective_config)
    safe_title = safe_title[: naming.get("safe_title_max_length", 80)]
    return pattern.format(
        index=index,
        video_id=video_id,
        safe_title=safe_title,
        title=title,
    )


def normalize_source_url(url: str) -> str:
    return url.strip()


_VALID_SOURCE_TYPES: frozenset[str] = frozenset(
    {"single", "search", "playlist", "channel", "unknown"}
)


def normalize_source_type(source_type: str) -> SourceType:
    return source_type if source_type in _VALID_SOURCE_TYPES else "unknown"  # type: ignore[return-value]


def build_manifest_entry(
    index: int,
    video_id: str,
    title: str,
    url: str,
    config: dict[str, Any] | None = None,
    source_type: str = "single",
) -> ManifestEntry:
    entry_input = ManifestEntryInput(
        index=index,
        video_id=video_id,
        title=title,
        url=url,
        source_type=source_type,
        config=config,
    )
    effective_config = entry_input.config or load_config()
    normalized_source_type = normalize_source_type(entry_input.source_type)
    return ManifestEntry(
        index=entry_input.index,
        video_id=entry_input.video_id,
        title=entry_input.title,
        url=entry_input.url,
        folder_name=build_item_folder_name(
            entry_input.index,
            entry_input.video_id,
            entry_input.title,
            config=effective_config,
        ),
        source_type=normalized_source_type,
    )
