"""Transcript worker entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# isort: off
# ROOT must be added to sys.path before importing config; keep these together
# so Ruff's import-sorter never hoists the import above the path mutation.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORKER_DIR = Path(__file__).resolve().parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from transcript_helpers import (  # noqa: E402
    TranscriptResult,
    TranscriptedItem,
    build_item_output_dir,
    build_transcript_input,
    fetch_subtitles_from_url,
    find_subtitle_files,
    find_transcript_output_path,
    load_manifest,
    write_transcript_from_subtitles,
)
from config.config_loader import load_config  # noqa: E402
# isort: on


def _build_item_result(
    entry: dict[str, Any],
    transcript_path: Path,
    *,
    status: str,
    error: str | None = None,
) -> TranscriptedItem:
    return TranscriptedItem(
        index=int(entry["index"]),
        video_id=str(entry["video_id"]),
        title=str(entry["title"]),
        url=str(entry["url"]),
        folder_name=str(entry["folder_name"]),
        transcript_path=str(transcript_path),
        status=status,
        error=error,
    )


def _process_item_entry(
    entry: dict[str, Any],
    resolved_output_dir: Path,
    transcript_input: Any,
    config: dict[str, Any],
) -> TranscriptedItem:
    item_dir = build_item_output_dir(resolved_output_dir, entry["folder_name"])
    transcript_path = find_transcript_output_path(item_dir, transcript_input.output_text_file)

    if not item_dir.exists():
        return _build_item_result(entry, transcript_path, status="skipped")

    if transcript_path.exists():
        return _build_item_result(entry, transcript_path, status="transcribed")

    subtitle_files = find_subtitle_files(item_dir)
    fetch_error: str | None = None

    if not subtitle_files:
        subtitle_languages = config.get("download", {}).get("subtitle_languages", ["en"])

        if transcript_input.prefer_manual_subtitles:
            fetch_error = fetch_subtitles_from_url(
                entry["url"], item_dir, subtitle_languages, auto_generated=False
            )
            subtitle_files = find_subtitle_files(item_dir)

        if not subtitle_files and transcript_input.fallback_to_auto_subtitles:
            fetch_error = fetch_subtitles_from_url(
                entry["url"], item_dir, subtitle_languages, auto_generated=True
            )
            subtitle_files = find_subtitle_files(item_dir)

    if subtitle_files:
        write_transcript_from_subtitles(item_dir, transcript_path, subtitle_files)
        return _build_item_result(entry, transcript_path, status="transcribed")

    if fetch_error:
        return _build_item_result(entry, transcript_path, status="failed", error=fetch_error)

    return _build_item_result(entry, transcript_path, status="skipped")


def build_transcript_manifest(
    manifest_path: Path | None = None,
    output_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> TranscriptResult:
    effective_config = config or load_config()
    transcript_input = build_transcript_input(effective_config)

    resolved_output_dir = output_dir or Path(effective_config["paths"]["jobs_root"])
    resolved_manifest_path = manifest_path or (resolved_output_dir / "conversion_manifest.json")

    if not resolved_manifest_path.exists():
        raise FileNotFoundError(f"Conversion manifest not found: {resolved_manifest_path}")

    manifest_entries = load_manifest(resolved_manifest_path)
    items = [
        _process_item_entry(entry, resolved_output_dir, transcript_input, effective_config)
        for entry in manifest_entries
    ]

    return TranscriptResult(
        manifest_path=str(resolved_manifest_path),
        output_dir=str(resolved_output_dir),
        items=items,
    )


def write_transcript_manifest(result: TranscriptResult, output_path: Path | None = None) -> Path:
    if output_path is None:
        output_path = Path(result.output_dir) / "transcript_manifest.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([item.model_dump() for item in result.items], indent=2),
        encoding="utf-8",
    )
    return output_path


def run() -> Path:
    result = build_transcript_manifest()
    return write_transcript_manifest(result)


if __name__ == "__main__":
    output_path = run()
    print(output_path)
